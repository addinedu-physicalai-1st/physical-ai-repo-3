// 마이크 PCM → openwakeword streaming KWS ("주문할게요") 감지.
// 게이팅은 robot_arm_project/kws/kws_v1.py 와 동일, streaming 처리는
// openwakeword/utils.py _streaming_features 그대로 이식.
(() => {
  const indicator = document.getElementById('voice-indicator');
  const startBtn = document.getElementById('mic-start-btn');
  if (!startBtn) {
    console.warn('[voice] #mic-start-btn 없음 — kiosk.html 수정 누락');
    return;
  }

  function setState(state) {
    if (!indicator) return;
    indicator.className = 'voice-ind ' + state;
    indicator.dataset.state = state;
  }
  setState('idle');

  const MODELS_BASE = '/order_vui/shared/models';

  const KWS_THRESHOLD = 0.65;
  // 합성 TTS 학습 모델 + 사람 발화는 high 청크가 단발성이라 1 청크만 통과해도 트리거.
  const KWS_CONSEC = 1;
  const KWS_COOLDOWN_SEC = 2.5;

  // 마이크 입력 증폭. 너무 크면 clip 발생.
  const MIC_GAIN = 1.5;

  // openwakeword streaming 상수
  const RAW_INPUT_LEN = 1280 + 160 * 3; // 1760 samples
  const MEL_FRAMES_WIN = 76;
  const MEL_FRAMES_STEP = 8;
  const EMB_BUFFER_LEN = 16;

  let audioCtx = null;
  let stream = null;
  let workletNode = null;

  let melSession = null;
  let embSession = null;
  let kwsSession = null;

  let rawBuf = new Float32Array(0);
  let melBuf = [];
  let embBuf = [];
  let kwsHitBuf = [];
  let lastTriggerTs = 0;
  let busy = false;

  // KWS 학습 분포(raw PCM + SNR augmentation)에 맞추기 위해 브라우저 신호 처리 OFF.
  const baseAudioConstraints = {
    channelCount: 1,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: true,
  };

  async function fetchBuf(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`fetch ${path} -> HTTP ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
  }

  async function loadSession(label, modelPath, externalDataPaths) {
    const modelBuf = await fetchBuf(modelPath);
    const opts = { executionProviders: ['wasm'] };
    if (externalDataPaths && externalDataPaths.length) {
      const externalData = [];
      for (const ext of externalDataPaths) {
        externalData.push({ path: ext.path, data: await fetchBuf(ext.url) });
      }
      opts.externalData = externalData;
    }
    const sess = await ort.InferenceSession.create(modelBuf, opts);
    console.log(`[voice] loaded ${label}: in=${sess.inputNames} out=${sess.outputNames}`);
    return sess;
  }

  async function loadModels() {
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.simd = true;
    melSession = await loadSession('mel', `${MODELS_BASE}/melspectrogram.onnx`);
    embSession = await loadSession('embedding', `${MODELS_BASE}/embedding_model.onnx`);
    kwsSession = await loadSession('kws', `${MODELS_BASE}/kws_v1.onnx`, [
      { path: 'kws_v1.onnx.data', url: `${MODELS_BASE}/kws_v1.onnx.data` },
    ]);
  }

  async function acquireMic() {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: baseAudioConstraints });
      const t = s.getAudioTracks()[0];
      console.log(`[voice] mic acquired (default): "${t && t.label ? t.label : '(no-label)'}"`);
      return s;
    } catch (e) {
      console.warn(`[voice] default mic failed: ${e.name || ''} ${e.message || ''} — enumerate fallback`);
    }
    const devs = await navigator.mediaDevices.enumerateDevices();
    const inputs = devs.filter((d) => d.kind === 'audioinput' && d.deviceId);
    for (const dev of inputs) {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          audio: { ...baseAudioConstraints, deviceId: { exact: dev.deviceId } },
        });
        const t = s.getAudioTracks()[0];
        console.log(`[voice] mic acquired (fallback): "${t && t.label ? t.label : dev.label}"`);
        return s;
      } catch (e) {
        console.warn(`[voice] device "${dev.label || dev.deviceId}" failed: ${e.name || e}`);
      }
    }
    throw new Error('사용 가능한 마이크를 찾을 수 없습니다.');
  }

  function appendFloat(src) {
    const out = new Float32Array(rawBuf.length + src.length);
    out.set(rawBuf, 0);
    out.set(src, rawBuf.length);
    if (out.length > RAW_INPUT_LEN) {
      return out.slice(out.length - RAW_INPUT_LEN);
    }
    return out;
  }

  // openwakeword 는 int16 값을 그대로 float32 로 cast (스케일 유지)
  function int16ToFloat32(int16) {
    const f = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f[i] = int16[i];
    return f;
  }

  async function processChunk(int16Chunk) {
    if (busy) return;
    if (!melSession || !embSession || !kwsSession) return;
    busy = true;
    try {
      rawBuf = appendFloat(int16ToFloat32(int16Chunk));
      if (rawBuf.length < RAW_INPUT_LEN) return;

      // 1) mel
      const melIn = new ort.Tensor('float32', rawBuf.slice(), [1, rawBuf.length]);
      const melOut = await melSession.run({ [melSession.inputNames[0]]: melIn });
      const melT = melOut[melSession.outputNames[0]];
      const melData = melT.data;
      const melDims = melT.dims;
      let nFrames, nMels;
      if (melDims.length === 3) { nFrames = melDims[1]; nMels = melDims[2]; }
      else if (melDims.length === 4) { nFrames = melDims[2]; nMels = melDims[3]; }
      else return;

      // openwakeword 의 melspec_transform: x / 10 + 2 — 누락 시 학습 분포와 어긋남
      const start = Math.max(0, nFrames - MEL_FRAMES_STEP);
      for (let i = start; i < nFrames; i++) {
        const frame = new Float32Array(nMels);
        for (let j = 0; j < nMels; j++) frame[j] = melData[i * nMels + j] / 10 + 2;
        melBuf.push(frame);
      }
      while (melBuf.length > MEL_FRAMES_WIN) melBuf.shift();
      if (melBuf.length < MEL_FRAMES_WIN) return;

      // 2) embedding
      const embIn = new Float32Array(MEL_FRAMES_WIN * nMels);
      for (let i = 0; i < MEL_FRAMES_WIN; i++) {
        const f = melBuf[i];
        for (let j = 0; j < nMels; j++) embIn[i * nMels + j] = f[j];
      }
      const embInTensor = new ort.Tensor('float32', embIn, [1, MEL_FRAMES_WIN, nMels, 1]);
      const embOutObj = await embSession.run({ [embSession.inputNames[0]]: embInTensor });
      const embT = embOutObj[embSession.outputNames[0]];
      const embFlat = new Float32Array(embT.data);
      embBuf.push(embFlat);
      while (embBuf.length > EMB_BUFFER_LEN) embBuf.shift();
      if (embBuf.length < EMB_BUFFER_LEN) return;

      // 3) kws
      const embLen = embBuf[0].length;
      const kwsIn = new Float32Array(EMB_BUFFER_LEN * embLen);
      for (let i = 0; i < EMB_BUFFER_LEN; i++) kwsIn.set(embBuf[i], i * embLen);
      const kwsInTensor = new ort.Tensor('float32', kwsIn, [1, EMB_BUFFER_LEN, embLen]);
      const kwsOut = await kwsSession.run({ [kwsSession.inputNames[0]]: kwsInTensor });
      const kwsData = kwsOut[kwsSession.outputNames[0]].data;
      const score = kwsData[kwsData.length - 1];

      // 4) 게이팅
      const now = performance.now() / 1000;
      if (now - lastTriggerTs < KWS_COOLDOWN_SEC) {
        kwsHitBuf = [];
        return;
      }
      kwsHitBuf.push(score >= KWS_THRESHOLD);
      while (kwsHitBuf.length > KWS_CONSEC) kwsHitBuf.shift();
      const triggered = kwsHitBuf.length === KWS_CONSEC && kwsHitBuf.every(Boolean);
      if (triggered) {
        lastTriggerTs = now;
        kwsHitBuf = [];
        onWakeWord(score);
      }
    } catch (e) {
      console.error('[voice] inference error:', e);
    } finally {
      busy = false;
    }
  }

  function onWakeWord(score) {
    console.log(`[voice] wake word triggered  score=${score.toFixed(3)}`);
    setState('thinking');
    const audio = new Audio('/audio/001.wav');
    audio.play().catch((e) => console.warn('[voice] start tone play failed:', e));
    setTimeout(() => setState('listening'), 1500);
  }

  async function start() {
    if (audioCtx) return;
    startBtn.disabled = true;
    startBtn.textContent = '모델 로드 중...';
    try {
      await loadModels();
      startBtn.textContent = '마이크 시작 중...';
      stream = await acquireMic();
      try {
        audioCtx = new AudioContext({ sampleRate: 16000 });
      } catch (_) {
        audioCtx = new AudioContext();
        console.warn('[voice] 16kHz AudioContext 실패 — 시스템 기본값으로 생성됨');
      }
      console.log(`[voice] ctxSampleRate=${audioCtx.sampleRate}`);
      if (audioCtx.sampleRate !== 16000) {
        console.warn(`[voice] ctxSampleRate(${audioCtx.sampleRate}) != 16000 — KWS 정확도 낮을 수 있음`);
      }
      await audioCtx.audioWorklet.addModule('/order_vui/shared/voice_worklet.js');
      const src = audioCtx.createMediaStreamSource(stream);
      const gainNode = audioCtx.createGain();
      gainNode.gain.value = MIC_GAIN;
      workletNode = new AudioWorkletNode(audioCtx, 'pcm-capture');
      workletNode.port.onmessage = (e) => {
        processChunk(e.data);
      };
      src.connect(gainNode);
      gainNode.connect(workletNode);
      console.log(`[voice] MIC_GAIN=${MIC_GAIN}`);

      setState('listening');
      startBtn.classList.add('on');
      startBtn.textContent = '마이크 ON (다시 누르면 정지)';
      startBtn.disabled = false;
      console.log('[voice] mic + KWS started — say "주문할게요"');
    } catch (e) {
      console.error('[voice] start failed:', e);
      await stop();
      alert('시작 실패: ' + (e && e.message ? e.message : e));
    }
  }

  async function stop() {
    if (workletNode) { try { workletNode.disconnect(); } catch (_) {} workletNode = null; }
    if (audioCtx) { try { await audioCtx.close(); } catch (_) {} audioCtx = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    rawBuf = new Float32Array(0);
    melBuf = [];
    embBuf = [];
    kwsHitBuf = [];
    busy = false;
    setState('idle');
    startBtn.disabled = false;
    startBtn.classList.remove('on');
    startBtn.textContent = '마이크 시작';
    console.log('[voice] mic stopped');
  }

  startBtn.addEventListener('click', () => {
    if (audioCtx) stop(); else start();
  });
})();

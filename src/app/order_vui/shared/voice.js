// 마이크 PCM → openwakeword streaming KWS ("주문할게요") 감지.
// wake word 트리거 시 silero-vad-web 으로 발화 끝 감지 → ASR → LLM → handleIntent.
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
  const VOICE_SERVICE_URL = window.VOICE_SERVICE_URL || 'http://192.168.0.133:8010';

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

  // ASR context hint — 메뉴/알러지 외에 키오스크에서 자주 나오는 발화 어휘.
  // 메뉴/알러지명은 호출 시점에 동적으로 합쳐 보낸다.
  const ASR_KEYWORDS = [
    '주문할게요', '한 잔', '두 잔', '세 잔',
    '따뜻하게', '차갑게', '뜨겁게',
    '샷 추가', '얼음 빼', '얼음 없이',
    '다음으로', '결제할게', '주문 확인할게',
    '뒤로', '다시 고를래',
    '알러지 없어요', '확인했어',
  ];

  // unknown intent 자동 재시도. wake 한 번에 최대 N 회까지, 매 회 무발화 timeout.
  const UNKNOWN_RETRY_MAX = 2;
  const UNKNOWN_RETRY_TIMEOUT_MS = 10000;

  // VAD CDN (잘 동작 확인되면 자체 호스팅으로 옮길 것)
  const VAD_ASSET_BASE = 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.22/dist/';
  const VAD_ORT_BASE = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/';

  let audioCtx = null;
  let stream = null;
  let workletNode = null;

  let melSession = null;
  let embSession = null;
  let kwsSession = null;

  let vadInstance = null;
  let vadBusy = false;  // VAD active 또는 ASR/LLM 처리 중이면 KWS 게이트 차단
  let retryCount = 0;   // unknown 자동 재시도 카운터 (wake 마다 0 으로 리셋)
  let retryTimer = null;

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

  async function loadVAD() {
    if (vadInstance) return;
    if (!window.vad || !window.vad.MicVAD) {
      throw new Error('@ricky0123/vad-web 가 로드되지 않음 — kiosk.html 의 vad-web script 확인');
    }
    vadInstance = await window.vad.MicVAD.new({
      baseAssetPath: VAD_ASSET_BASE,
      onnxWASMBasePath: VAD_ORT_BASE,
      positiveSpeechThreshold: 0.5,
      negativeSpeechThreshold: 0.35,
      minSpeechFrames: 4,         // 너무 짧은 잡음 제외 (~128ms)
      redemptionFrames: 24,       // 발화 끝 판정 후 ~768ms 여유
      onSpeechStart: () => {
        setState('listening');
        console.log('[vad] speech start');
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
      },
      onSpeechEnd: async (audio) => {
        console.log(`[vad] speech end, ${audio.length} samples`);
        try { vadInstance.pause(); } catch (_) {}
        await processUtterance(audio);
      },
      onVADMisfire: () => {
        console.log('[vad] misfire (너무 짧은 발화)');
        try { vadInstance.pause(); } catch (_) {}
        setState('idle');
        vadBusy = false;
      },
    });
    console.log('[vad] loaded');
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
    if (vadBusy) return;  // VAD 또는 ASR/LLM 처리 중이면 KWS 무시
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
    vadBusy = true;
    retryCount = 0;
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    setState('thinking');
    const audio = new Audio('/audio/001.wav');
    audio.play().catch((e) => console.warn('[voice] start tone play failed:', e));
    // 시작음과 사용자 발화가 겹치지 않게 약 1.2초 후 VAD 시작
    setTimeout(async () => {
      try {
        if (!vadInstance) await loadVAD();
        vadInstance.start();
        setState('listening');
      } catch (e) {
        console.error('[voice] VAD start failed:', e);
        vadBusy = false;
        setState('idle');
      }
    }, 1200);
  }

  async function processUtterance(audioFloat32) {
    setState('thinking');
    let intent = null;
    try {
      const wav = encodeWav(audioFloat32, 16000);

      // kiosk.html 의 전역 변수들은 let 으로 선언돼 window.X 로는 접근 불가
      // — 같은 글로벌 스크립트 환경이라 식별자로는 참조 가능.
      const csName = (typeof currentScreen !== 'undefined') ? currentScreen : null;
      const mnList = (typeof MENU !== 'undefined' && Array.isArray(MENU)) ? MENU : [];
      const ctList = (typeof cart !== 'undefined' && Array.isArray(cart)) ? cart : [];
      const alList = (typeof ALLERGY_INFO !== 'undefined' && Array.isArray(ALLERGY_INFO)) ? ALLERGY_INFO : [];

      // ASR context 구성: 도메인 톤 + 현재 메뉴 (별칭 포함) + 알러지 + 키오스크 어휘
      const ctxParts = ['카페 키오스크 음성 주문.'];
      if (mnList.length) {
        const menuStrs = mnList.map((m) => {
          const ali = Array.isArray(m.aliases) && m.aliases.length ? ` (${m.aliases.join(', ')})` : '';
          return m.name + ali;
        });
        ctxParts.push('메뉴: ' + menuStrs.join(', ') + '.');
      }
      if (alList.length) ctxParts.push('알러지: ' + alList.map((a) => a.name).join(', ') + '.');
      ctxParts.push('자주 쓰는 말: ' + ASR_KEYWORDS.join(', ') + '.');
      const asrContext = ctxParts.join(' ');

      const fd = new FormData();
      fd.append('file', new Blob([wav], { type: 'audio/wav' }), 'utt.wav');
      fd.append('context', asrContext);
      const asrRes = await fetch(`${VOICE_SERVICE_URL}/asr/transcribe`, { method: 'POST', body: fd });
      if (!asrRes.ok) throw new Error(`ASR HTTP ${asrRes.status}`);
      const asr = await asrRes.json();
      console.log(`[asr] "${asr.text}" (${asr.latency_ms.toFixed(0)}ms)`);

      const llmRes = await fetch(`${VOICE_SERVICE_URL}/llm/intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_text: asr.text,
          current_screen: csName,
          cart: ctList,
          menu: mnList.map((m) => ({ name: m.name })),
          allergies: alList.map((a) => a.name),
        }),
      });
      if (!llmRes.ok) throw new Error(`LLM HTTP ${llmRes.status}`);
      intent = await llmRes.json();
      console.log(`[llm] intent=${intent.intent} (${intent.latency_ms.toFixed(0)}ms)`);

      if (typeof window.handleIntent === 'function') {
        window.handleIntent(intent);
      } else {
        console.warn('[voice] handleIntent 미정의 — intent_handler.js 누락?');
      }
    } catch (e) {
      console.error('[voice] processUtterance error:', e);
    } finally {
      const shouldRetry = !!intent && intent.intent === 'unknown' && retryCount < UNKNOWN_RETRY_MAX;
      if (shouldRetry) {
        retryCount++;
        console.log(`[voice] unknown — auto retry ${retryCount}/${UNKNOWN_RETRY_MAX} (timeout ${UNKNOWN_RETRY_TIMEOUT_MS}ms)`);
        try {
          vadInstance.start();
          setState('listening');
          if (retryTimer) clearTimeout(retryTimer);
          retryTimer = setTimeout(() => {
            console.log('[voice] unknown retry timeout — idle');
            try { vadInstance.pause(); } catch (_) {}
            setState('idle');
            vadBusy = false;
            retryCount = 0;
            retryTimer = null;
          }, UNKNOWN_RETRY_TIMEOUT_MS);
        } catch (e) {
          console.error('[voice] retry VAD start failed:', e);
          setState('idle');
          vadBusy = false;
          retryCount = 0;
        }
      } else {
        setState('idle');
        vadBusy = false;
        retryCount = 0;
      }
    }
  }

  // Float32Array @ sampleRate → 16-bit PCM mono WAV (Uint8Array).
  function encodeWav(samples, sampleRate) {
    const numSamples = samples.length;
    const bytesPerSample = 2;
    const blockAlign = bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = numSamples * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);
    const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };

    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, dataSize, true);

    let off = 44;
    for (let i = 0; i < numSamples; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      off += 2;
    }
    return new Uint8Array(buffer);
  }

  async function start() {
    if (audioCtx) return;
    startBtn.disabled = true;
    startBtn.textContent = '모델 로드 중...';
    try {
      await loadModels();
      // VAD 도 미리 로드해서 첫 wake 후 추가 지연 없게
      try { await loadVAD(); } catch (e) { console.warn('[voice] VAD 미리 로드 실패 (첫 wake 때 재시도):', e); }

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
      console.log(`[voice] VOICE_SERVICE_URL=${VOICE_SERVICE_URL}`);

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
    if (vadInstance) {
      try { vadInstance.pause(); } catch (_) {}
    }
    if (workletNode) { try { workletNode.disconnect(); } catch (_) {} workletNode = null; }
    if (audioCtx) { try { await audioCtx.close(); } catch (_) {} audioCtx = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    rawBuf = new Float32Array(0);
    melBuf = [];
    embBuf = [];
    kwsHitBuf = [];
    busy = false;
    vadBusy = false;
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

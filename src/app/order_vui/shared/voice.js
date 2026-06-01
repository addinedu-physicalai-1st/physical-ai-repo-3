// 마이크 PCM → openwakeword streaming KWS ("주문할게요") 감지.
// wake word 트리거 시 silero-vad-web 으로 발화 끝 감지 → ASR → LLM → handleIntent.
// 게이팅은 robot_arm_project/kws/kws_v1.py 와 동일, streaming 처리는
// openwakeword/utils.py _streaming_features 그대로 이식.
(() => {
  const indicator = document.getElementById('voice-indicator');
  const startBtn = document.getElementById('mic-start-btn');
  const pttBtn = document.getElementById('ptt-btn');
  // table 모드: window.VOICE_MODE='table' 면 PTT 버튼 사용, KWS 우회.
  const IS_TABLE = (window.VOICE_MODE === 'table');
  if (!IS_TABLE && !startBtn) {
    console.warn('[voice] #mic-start-btn 없음 — kiosk.html 수정 누락');
    return;
  }
  if (IS_TABLE && !pttBtn) {
    console.warn('[voice] table 모드인데 #ptt-btn 없음 — table.html 수정 누락');
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

  // voice_service 호출 타임아웃 — 응답이 없을 때 무한 대기 방지.
  // 정상 흐름은 1~2 초 안에 끝나므로 99% 케이스엔 영향 없음.
  const ASR_TIMEOUT_MS = 8000;
  const LLM_TIMEOUT_MS = 8000;
  const TTS_TIMEOUT_MS = 10000;

  // 키오스크 wake 후 follow-up listening 동안 30 초 무발화면 자동 standby 복귀.
  // 손님이 자리를 뜬 채로 listening 상태가 영원히 유지되는 것을 막는다.
  // table(PTT) 모드는 wake/follow-up 흐름이 없어 적용 대상 아님.
  const IDLE_TIMEOUT_MS = 30000;

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

  // ASR context: 도메인 톤 + 정식 명칭(별명 포함). 알러지명/어휘는 제외.
  // Qwen3-ASR 의 context 인자는 정확도 향상의 핵심 메커니즘이므로 풍부하게 넘긴다.
  // 다만 빈 발화 시 ASR 가 context 를 그대로 echo 해 LLM 이 add_menu 로 오분류하는
  // leakage 가 발생할 수 있어, voice_service prompts.py 의 시스템 프롬프트에
  // "콤마 명사구 나열 형태이면 unknown" 방어를 같이 두었다.
  // 단일 진실: web_service menu_service.py list_menu() MenuItem(name, aliases) → /api/menu → MENU 전역 → 여기로 전파.
  const ASR_CONTEXT_PREFIX = '카페 키오스크 주문.';
  // 수량/세는 말도 ASR 바이어싱에 넣어 "두 개"를 "두게", "세 개"를 "새개" 등으로 잘못 받아쓰는 것을 줄인다.
  // 메뉴 별명(aliases)이 아니라 ASR 컨텍스트 영역이다 — LLM 은 수량을 이미 잘 파싱하므로 ASR 입력 품질만 올리면 된다.
  // 라벨 "자주 쓰는 말:" 은 prompts.py 의 'ASR context echo 차단' 규칙이 인식하는 라벨이라 echo 시 unknown 처리된다.
  const ASR_COUNT_CONTEXT =
    '자주 쓰는 말: 하나, 한 개, 한 잔, 둘, 두 개, 두 잔, 셋, 세 개, 세 잔, 넷, 네 개, 다섯, 다섯 개, 개, 잔, '
    + '맞아, 맞아요, 네, 응, 좋아요, 확인했어요, 주문할게요, 주문 확인, 다음, 다음으로, 뒤로, 이전, 취소, 안 할래요, '
    + '추가, 빼 주세요, 적게, 많이, 주세요, 해 주세요.';

  // 폰에서 ASR/LLM 결과를 눈으로 보기 위한 디버그 오버레이.
  // URL 에 ?debug=1 (또는 &debug=1) 이 있을 때만 화면 하단에 "들림/의도/에러" 롤링 로그 표시.
  // 손님이 보는 일반 주문에는 영향 없음. 무엇을 잘못 받아쓰는지 바로 확인해 컨텍스트를 정밀 보강하는 용도.
  const VOICE_DEBUG = new URLSearchParams(location.search).has('debug');
  function _voiceDebugEl() {
    let el = document.getElementById('voice-debug');
    if (!el) {
      el = document.createElement('div');
      el.id = 'voice-debug';
      el.style.cssText = 'position:fixed;left:8px;right:8px;bottom:128px;z-index:1000;'
        + 'background:rgba(0,0,0,0.88);color:#39ff6a;font:12px/1.45 monospace;'
        + 'padding:8px 10px;border-radius:8px;white-space:pre-wrap;pointer-events:none;'
        + 'max-height:42vh;overflow:hidden;';
      el.innerHTML = '<div id="voice-debug-status" style="color:#ffd479;border-bottom:1px solid #555;'
        + 'padding-bottom:4px;margin-bottom:4px;"></div><div id="voice-debug-log"></div>';
      document.body.appendChild(el);
    }
    return el;
  }
  // 고정 상태줄(제자리 갱신): 마이크 입력 % 처럼 자주 바뀌는 값. 로그를 밀어내지 않는다.
  function voiceDebugStatus(msg) {
    if (!VOICE_DEBUG) return;
    _voiceDebugEl();
    const s = document.getElementById('voice-debug-status');
    if (s) s.textContent = msg;
  }
  // 이벤트 로그(위로 쌓임): 들림(인식)/의도/발화/에러 — 상태줄과 분리해 사라지지 않게.
  function voiceDebugLog(msg) {
    if (!VOICE_DEBUG) return;
    _voiceDebugEl();
    const logEl = document.getElementById('voice-debug-log');
    if (!logEl) return;
    const prev = logEl.textContent ? logEl.textContent.split('\n') : [];
    logEl.textContent = [msg, ...prev].slice(0, 10).join('\n');
  }

  // wake 한 번 → 여러 발화 follow-up. 외부에서 window.voiceIdle() 을 호출할 때까지 listening 유지.
  // (주문번호 화면 도달 시 kiosk 측에서 명시적으로 voiceIdle 호출)

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
  let _vadPeak = 0, _vadFrames = 0;  // 디버그: 마이크 입력 발화확률 추적 (?debug 시에만 사용)
  let vadBusy = false;  // VAD active 또는 ASR/LLM 처리 중이면 KWS 게이트 차단
  let ttsSpeaking = false;  // TTS 재생 중 — KWS/VAD 모두 차단해 echo 방지
  let turnCount = 0;    // wake 후 처리한 발화 수 (정보 로그용, 매 wake 마다 0)
  let idleTimer = null; // 무발화 30초 standby 복귀 타이머 (kiosk only)
  let lastActivityTs = 0; // 마지막 유효 intent 시점. 잡음/leak (unknown) 은 갱신 안 함.

  let rawBuf = new Float32Array(0);
  let melBuf = [];
  let embBuf = [];
  let kwsHitBuf = [];
  let lastTriggerTs = 0;
  let busy = false;

  // table 모드: 탭으로 음성 세션 시작/종료. 세션 중에는 kiosk 와 동일하게
  // VAD 가 발화 끝을 자동 감지하고 ASR/LLM/TTS 후 다음 발화로 멀티턴 이어진다.
  let tableSessionActive = false;

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

  // AbortController 기반 타임아웃 wrapper. 시간 초과 시 AbortError 가 throw 된다.
  async function fetchWithTimeout(url, opts, timeoutMs, label) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } catch (e) {
      if (e && e.name === 'AbortError') {
        throw new Error(`${label || 'fetch'} timeout (${timeoutMs}ms)`);
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
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
    if (IS_TABLE) {
      // PTT 모드는 KWS 불필요 — 모델 다운로드/로드 생략.
      console.log('[voice] table 모드: KWS 모델 로드 생략 (PTT 흐름)');
      return;
    }
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
      positiveSpeechThreshold: 0.5,   // 폰 마이크(거리/볼륨 낮음) 대응 0.7→0.5. 너무 낮으면 잡음 오감지↑
      negativeSpeechThreshold: 0.25,
      minSpeechFrames: 4,             // 8→4 (~256ms→~128ms): "커피" 처럼 무성음(ㅋ/ㅍ) 많아 voiced 구간 짧은
                                      // 발화가 misfire(너무 짧음)로 잘리던 문제 대응. 너무 낮추면 잡음 오감지↑
      redemptionFrames: 24,           // 발화 끝 판정 후 ~768ms 여유
      onSpeechStart: () => {
        clearIdleTimer();
        setState('listening');
        console.log('[vad] speech start');
        voiceDebugLog('발화 시작 감지');
      },
      onSpeechEnd: async (audio) => {
        console.log(`[vad] speech end, ${audio.length} samples`);
        voiceDebugLog(`발화 끝: ${audio.length}샘플 → ASR`);
        try { vadInstance.pause(); } catch (_) {}
        await processUtterance(audio);
      },
      onVADMisfire: () => {
        console.log('[vad] misfire (너무 짧은 발화) — listening 유지');
        voiceDebugLog('너무 짧음(misfire) — 다시 말하세요');
        // 발화가 너무 짧아 무시. 같은 wake 안에서는 listening 으로 다시 진입.
        try {
          vadInstance.pause();
          vadInstance.start();
          setState('listening');
          armIdleTimer();
        } catch (e) {
          setState('idle');
          vadBusy = false;
        }
      },
      // 디버그 전용: 매 프레임 발화확률의 ~1초 최고치를 오버레이에 찍어 마이크 입력 여부/임계값 진단.
      // 0% → 마이크 무음(입력 안 들어옴), 40~60% → 임계값(0.7) 너무 높음, 70%↑ → 감지는 정상.
      onFrameProcessed: (probs) => {
        if (!VOICE_DEBUG) return;
        const p = (probs && typeof probs.isSpeech === 'number') ? probs.isSpeech : 0;
        if (p > _vadPeak) _vadPeak = p;
        if (++_vadFrames % 15 === 0) {
          voiceDebugStatus(`🎤 발화확률 최고 ${(_vadPeak * 100).toFixed(0)}% (감지기준 50%)`);
          _vadPeak = 0;
        }
      },
    });
    console.log('[vad] loaded');
    voiceDebugLog('VAD 준비됨 (모델 로드 OK)');
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
    if (IS_TABLE) {
      // table 모드는 KWS 를 쓰지 않는다 — 음성 세션은 VAD 가 직접 마이크를 잡고 처리.
      return;
    }
    if (busy) return;
    if (!melSession || !embSession || !kwsSession) return;
    if (vadBusy) return;  // VAD 또는 ASR/LLM 처리 중이면 KWS 무시
    if (ttsSpeaking) return;  // TTS 재생 중 자기 음성 echo 차단
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
    turnCount = 0;
    setState('thinking');
    // wake 시작음은 인디케이터 thinking → listening 색 변화로 대체 (화면 안내음과 겹침 방지).
    // 약 1.2초 후 VAD 시작 (화면 전환 안내음과 발화 간 짧은 여유)
    setTimeout(async () => {
      // standby 화면이면 wake 시작음 끝난 뒤 menu 정상 진입 (loadMenu + render + 안내음 순차).
      if (typeof currentScreen !== 'undefined' && currentScreen === 'screen-standby' &&
          typeof goToMenu === 'function') {
        try { await goToMenu(); } catch (e) { console.warn('[voice] goToMenu failed:', e); }
      }
      try {
        if (!vadInstance) await loadVAD();
        vadInstance.start();
        setState('listening');
        armIdleTimer();
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

      // ASR 바이어싱엔 손님이 실제로 말하는 한국어 형태만 넣는다.
      // 메뉴 정식명이 영어(hotdog/coke/coffee)면 한국어 발화 ASR 에 노이즈가 되므로 제외하고,
      // name 이 한글일 때만 포함한다. 별명(aliases, 한국어)은 항상 포함.
      // 결과 예: "메뉴: 핫도그, 핫독, 소시지, 콜라, 코카콜라, 커피, 아메리카노, 아메."
      const menuPart = mnList.length
        ? '메뉴: ' + mnList.map((m) => {
            const aliases = (Array.isArray(m.aliases) ? m.aliases : []).filter(Boolean);
            const nameHasHangul = /[가-힣]/.test(String(m.name || ''));
            const spoken = [...(nameHasHangul ? [m.name] : []), ...aliases];
            return (spoken.length ? spoken : [m.name]).join(', ');
          }).join(', ') + '.'
        : '';
      const asrContext = [ASR_CONTEXT_PREFIX, menuPart, ASR_COUNT_CONTEXT].filter(Boolean).join(' ');

      const fd = new FormData();
      fd.append('file', new Blob([wav], { type: 'audio/wav' }), 'utt.wav');
      fd.append('context', asrContext);
      const asrRes = await fetchWithTimeout(
        `${VOICE_SERVICE_URL}/asr/transcribe`,
        { method: 'POST', body: fd },
        ASR_TIMEOUT_MS,
        'ASR',
      );
      if (!asrRes.ok) throw new Error(`ASR HTTP ${asrRes.status}`);
      const asr = await asrRes.json();
      console.log(`[asr] "${asr.text}" (${asr.latency_ms.toFixed(0)}ms)`);
      voiceDebugLog(`들림: "${asr.text}"`);

      const llmRes = await fetchWithTimeout(
        `${VOICE_SERVICE_URL}/llm/intent`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_text: asr.text,
            current_screen: csName,
            cart: ctList,
            menu: mnList.map((m) => ({
              name: m.name,
              aliases: Array.isArray(m.aliases) ? m.aliases : [],
            })),
            allergies: alList.map((a) => a.name),
          }),
        },
        LLM_TIMEOUT_MS,
        'LLM',
      );
      if (!llmRes.ok) throw new Error(`LLM HTTP ${llmRes.status}`);
      intent = await llmRes.json();
      console.log(`[llm] intent=${intent.intent} (${intent.latency_ms.toFixed(0)}ms)`);
      voiceDebugLog(`의도: ${intent.intent}` + (Array.isArray(intent.items) && intent.items.length
        ? ` — ${intent.items.map((i) => `${i.menu_name}×${i.qty}`).join(', ')}` : ''));
      // 유효 의도가 분류된 경우만 손님 활동으로 인정 → idle 카운트 anchor 갱신.
      // 잡음/leak (intent='unknown') 은 anchor 유지 → 무발화 30초 카운트 잡음 사이클 사이에서도 이어짐.
      if (intent && intent.intent && intent.intent !== 'unknown') {
        noteActivity();
      }

      if (typeof window.handleIntent === 'function') {
        await window.handleIntent(intent, asr.text);
      } else {
        console.warn('[voice] handleIntent 미정의 — intent_handler.js 누락?');
      }

      // TTS 동적 응답 재생 (response_text 가 있을 때만). VAD 는 이 시점에 pause 상태.
      const ttsText = (intent && typeof intent.response_text === 'string') ? intent.response_text.trim() : '';
      if (ttsText) {
        try {
          await speak(ttsText);
        } catch (e) {
          console.warn('[voice] TTS 재생 실패:', e);
        }
      }
    } catch (e) {
      console.error('[voice] processUtterance error:', e);
      voiceDebugLog(`에러: ${(e && e.message) ? e.message : e}`);
      // 손님에게 무발화/오류 사실을 정형 TTS 한 마디로 안내.
      // 안내 자체가 또 실패하면 무한 루프 방지 위해 console.warn 까지만.
      try {
        await speak('죄송해요, 다시 말씀해 주세요');
      } catch (ttsErr) {
        console.warn('[voice] 에러 안내 TTS 재생 실패:', ttsErr);
      }
    } finally {
      // 세션이 살아있으면(kiosk: wake 후 / table: 탭 세션) 발화 끝마다 listening 자동 재진입(멀티턴).
      // 종료는 외부(window.voiceIdle, 화면 전환) 호출 또는 무발화 타이머.
      const sessionActive = !IS_TABLE || tableSessionActive;
      if (sessionActive) {
        try {
          vadInstance.start();
          setState('listening');
          turnCount++;
          armIdleTimer();
          console.log(`[voice] follow-up listening (turn ${turnCount})`);
        } catch (e) {
          console.error('[voice] follow-up VAD start failed:', e);
          if (IS_TABLE && typeof window.voiceIdle === 'function') {
            window.voiceIdle();
          } else {
            setState('idle');
            vadBusy = false;
            turnCount = 0;
          }
        }
      } else {
        setState('idle');
        vadBusy = false;
        turnCount = 0;
      }
    }
  }

  // intent.response_text → voice_service /tts/speak → <audio> 재생.
  // 재생 동안 ttsSpeaking=true 로 KWS/VAD 차단. window.speak 로 외부 호출도 허용 (예: intent_handler 의 차단 멘트).
  async function speak(text) {
    const cleaned = (text || '').trim();
    if (!cleaned) return;
    setState('speaking');
    ttsSpeaking = true;
    try {
      const fd = new FormData();
      fd.append('text', cleaned);
      const res = await fetchWithTimeout(
        `${VOICE_SERVICE_URL}/tts/speak`,
        { method: 'POST', body: fd },
        TTS_TIMEOUT_MS,
        'TTS',
      );
      if (!res.ok) throw new Error(`TTS HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      await new Promise((resolve) => {
        audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
        audio.onerror = (e) => { URL.revokeObjectURL(url); console.warn('[voice] audio error', e); resolve(); };
        audio.play().catch((e) => { console.warn('[voice] audio.play 실패', e); resolve(); });
      });
    } finally {
      ttsSpeaking = false;
    }
  }
  window.speak = speak;

  // 무발화 30초 standby 복귀 타이머 — kiosk only.
  // 잡음/오인식(unknown intent)이 들어와도 카운트가 리셋되지 않도록 lastActivityTs 기준 잔여 시간으로 카운트.
  // 유효 intent(add_menu, confirm_order 등) 가 들어와야만 noteActivity 가 호출되어 anchor 갱신.
  function clearIdleTimer() {
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  }
  function noteActivity() {
    lastActivityTs = Date.now();
  }
  function onIdleTimeout() {
    idleTimer = null;
    // 처리 중이면 standby 지연 — 1초 후 재확인. 발화/응답 중 갑작스러운 standby 방지.
    if (vadBusy || ttsSpeaking) {
      idleTimer = setTimeout(onIdleTimeout, 1000);
      return;
    }
    console.log('[voice] 무발화 30초 — standby 복귀');
    voiceDebugLog('무발화 30초 → 대기화면 복귀 (발화 미감지)');
    lastActivityTs = 0;
    if (typeof resetSession === 'function') {
      resetSession();   // 내부에서 showScreen('screen-standby') → window.voiceIdle 호출
    } else if (typeof window.voiceIdle === 'function') {
      window.voiceIdle();
    }
  }
  function armIdleTimer() {
    if (IS_TABLE && !tableSessionActive) return;
    clearIdleTimer();
    if (lastActivityTs === 0) lastActivityTs = Date.now(); // 첫 호출 시 anchor 초기화
    const remaining = lastActivityTs + IDLE_TIMEOUT_MS - Date.now();
    if (remaining <= 0) { onIdleTimeout(); return; }
    idleTimer = setTimeout(onIdleTimeout, remaining);
  }

  // 외부(kiosk.html showScreen 등)에서 호출하면 마이크를 멈추고 KWS 대기 상태로 돌린다.
  window.voiceIdle = function voiceIdle() {
    try { if (vadInstance) vadInstance.pause(); } catch (_) {}
    setState('idle');
    vadBusy = false;
    turnCount = 0;
    clearIdleTimer();
    lastActivityTs = 0;
    if (IS_TABLE) {
      // table 음성 세션 종료: 버튼 라벨/표시 원복.
      tableSessionActive = false;
      setPttLabel('탭하여 말하기');
      if (pttBtn) pttBtn.classList.remove('pressed');
    }
    console.log('[voice] voiceIdle — 음성 세션 종료/대기');
  };

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
    if (startBtn) { startBtn.disabled = true; startBtn.textContent = '모델 로드 중...'; }
    try {
      await loadModels();
      // VAD 미리 로드 — kiosk: 첫 wake 후 지연 방지 / table: 탭 즉시 listening.
      try { await loadVAD(); } catch (e) { console.warn('[voice] VAD 미리 로드 실패 (시작 시 재시도):', e); }

      if (startBtn) startBtn.textContent = '마이크 시작 중...';
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

      if (IS_TABLE) {
        // table 모드: 마이크/VAD 준비만 하고 대기. 실제 listening 은 탭(startTableSession)부터.
        setState('idle');
        console.log('[voice] mic ready (table mode — 탭하여 대화 시작)');
      } else {
        setState('listening');
        if (startBtn) {
          startBtn.classList.add('on');
          startBtn.textContent = '마이크 ON (다시 누르면 정지)';
          startBtn.disabled = false;
        }
        console.log('[voice] mic + KWS started — say "주문할게요"');
      }
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
    tableSessionActive = false;
    busy = false;
    vadBusy = false;
    clearIdleTimer();
    lastActivityTs = 0;
    setState('idle');
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.classList.remove('on');
      startBtn.textContent = '마이크 시작';
    }
    console.log('[voice] mic stopped');
  }

  // table 모드: 탭으로 음성 세션 시작/종료. kiosk 의 "wake → VAD 자동 대화" 흐름을
  // 웨이크워드 대신 버튼 탭으로 트리거한다.
  function setPttLabel(text) {
    if (!pttBtn) return;
    const label = pttBtn.querySelector('.ptt-label');
    if (label) label.textContent = text;
  }

  function endTableSession() {
    // voiceIdle 이 VAD pause + 상태/플래그/라벨 정리를 모두 담당.
    if (typeof window.voiceIdle === 'function') window.voiceIdle();
  }

  async function startTableSession() {
    if (ttsSpeaking) return;
    // table 은 KWS 를 안 쓰므로 KWS 마이크/AudioWorklet(start()) 을 타지 않는다.
    // VAD(MicVAD) 가 자체적으로 마이크를 잡는다 — 첫 탭(사용자 제스처) 안에서 로드.
    // (start() 경로는 폰에서 'pcm-capture' worklet 미등록으로 실패하므로 table 은 우회한다.)
    if (!vadInstance) {
      try {
        await loadVAD();
      } catch (e) {
        console.error('[voice] table 세션 VAD 로드 실패', e);
        voiceDebugLog(`VAD 로드 실패: ${(e && e.message) ? e.message : e}`);
        alert('마이크 시작 실패: ' + (e && e.message ? e.message : e));
        return;
      }
    }
    tableSessionActive = true;
    // table 은 KWS 가 없어 vadBusy 게이트가 불필요. false 로 둬야 무발화 30초 standby 타이머가
    // onIdleTimeout 에서 defer 되지 않고 실제로 동작한다 (VAD 자체는 vadBusy 와 무관하게 돈다).
    vadBusy = false;
    turnCount = 0;
    // standby 화면이면 메뉴로 진입 (kiosk wake 와 동일 경험).
    if (typeof currentScreen !== 'undefined' && currentScreen === 'screen-standby' &&
        typeof goToMenu === 'function') {
      try { await goToMenu(); } catch (e) { console.warn('[voice] goToMenu 실패:', e); }
    }
    try {
      vadInstance.start();
      setState('listening');
      armIdleTimer();
      voiceDebugLog('세션 시작 — 이제 말하세요');
    } catch (e) {
      console.error('[voice] table 세션 VAD start 실패:', e);
      voiceDebugLog(`VAD start 실패: ${(e && e.message) ? e.message : e}`);
      endTableSession();
      return;
    }
    setPttLabel('대화 중 · 탭하여 종료');
    if (pttBtn) pttBtn.classList.add('pressed');
    console.log('[voice] table 음성 세션 시작 (VAD 자동 대화)');
  }
  window.startTableSession = startTableSession;

  if (IS_TABLE) {
    // 탭 토글: 한 번 탭하면 음성 세션 시작(이후 VAD 자동 대화·멀티턴), 다시 탭하면 종료.
    // click 은 사용자 제스처라 iOS Safari 의 getUserMedia 권한 요건도 충족.
    pttBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (tableSessionActive) endTableSession();
      else startTableSession();
    });
    // iOS Safari 가 contextmenu 띄우는 것 차단
    pttBtn.addEventListener('contextmenu', (e) => e.preventDefault());
  } else {
    startBtn.addEventListener('click', () => {
      if (audioCtx) stop(); else start();
    });
  }
})();

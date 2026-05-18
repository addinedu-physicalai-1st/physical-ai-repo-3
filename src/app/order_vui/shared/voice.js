// Phase 0 mock — Phase 2 부터 실제 마이크 / KWS / voice_service 호출로 교체된다.
// URL 에 ?mock=1 이 있을 때만 5 초 루프가 돌아간다.
(() => {
  const indicator = document.getElementById('voice-indicator');

  function setState(state) {
    if (!indicator) return;
    indicator.className = 'voice-ind ' + state;
    indicator.dataset.state = state;
  }

  setState('idle');

  const params = new URLSearchParams(location.search);
  if (params.get('mock') !== '1') {
    console.log('[voice] mock loop disabled (use ?mock=1 to enable)');
    return;
  }

  console.log('[voice] mock loop enabled — adding 아메리카노 every 5s');

  let tick = 0;
  setInterval(() => {
    tick += 1;
    setState('listening');
    setTimeout(() => setState('thinking'), 600);
    setTimeout(() => {
      // MENU 는 kiosk.html 의 전역. 아메리카노가 보통 id=1.
      if (typeof MENU !== 'undefined' && Array.isArray(MENU) && MENU.length) {
        const amer = MENU.find(m => m && m.name && m.name.includes('아메리카노'));
        if (amer && typeof addToCart === 'function') {
          addToCart(amer.id);
          console.log(`[voice] mock tick ${tick}: addToCart(${amer.id})`);
        }
      }
      setState('speaking');
    }, 1200);
    setTimeout(() => setState('idle'), 2200);
  }, 5000);
})();

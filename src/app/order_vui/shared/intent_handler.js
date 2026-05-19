// LLM intent 응답을 키오스크 UI 액션으로 매핑.
(() => {
  // LLM 영문 enum → kiosk.html 옵션 한글 라벨
  const SHOT_MAP = { extra: '추가', less: '기본' };
  const ICE_MAP = { less: '얼음 없음', more: '각 얼음' };

  function addItems(items) {
    if (typeof addToCart !== 'function' || !Array.isArray(MENU)) {
      console.warn('[intent] addToCart/MENU 가 전역에 없음 — kiosk 컨텍스트가 아닙니다.');
      return;
    }
    for (const it of items || []) {
      const name = it && it.menu_name;
      if (!name) continue;
      const menu = MENU.find((m) => m.name === name);
      if (!menu) {
        console.warn(`[intent] 메뉴 매칭 실패: "${name}"`);
        continue;
      }
      const qty = Math.max(1, Math.floor(it.qty || 1));
      for (let i = 0; i < qty; i++) addToCart(menu.id);
      console.log(`[intent] add_menu: ${name} × ${qty}`);
    }
  }

  // set_option: 마지막 카트 아이템 대상 (menu_name 명시 시 그 메뉴 우선)
  function applyOptions(items) {
    if (typeof setOption !== 'function' || !Array.isArray(cart)) {
      console.warn('[intent] setOption/cart 가 전역에 없음');
      return;
    }
    if (cart.length === 0) {
      console.warn('[intent] set_option 인데 카트 비어있음');
      return;
    }
    for (const it of items || []) {
      const opts = (it && it.options) || {};
      let target = null;
      if (it && it.menu_name) {
        const menu = Array.isArray(MENU) ? MENU.find((m) => m.name === it.menu_name) : null;
        if (menu) target = cart.find((c) => c.menuId === menu.id);
      }
      if (!target) target = cart[cart.length - 1];
      if (!target) continue;

      if (opts.shot && SHOT_MAP[opts.shot]) {
        setOption(target.menuId, 'shot', SHOT_MAP[opts.shot]);
        console.log(`[intent] set_option shot=${SHOT_MAP[opts.shot]} (menuId=${target.menuId})`);
      }
      if (opts.ice && ICE_MAP[opts.ice]) {
        setOption(target.menuId, 'ice', ICE_MAP[opts.ice]);
        console.log(`[intent] set_option ice=${ICE_MAP[opts.ice]} (menuId=${target.menuId})`);
      }
      // temperature/milk 는 현재 UI 매핑 대상 아님 — 무시
    }
  }

  // back: 현재 화면 기준 이전 화면으로
  const BACK_MAP = {
    'screen-confirm': 'screen-menu',
    'screen-options': 'screen-confirm',
    'screen-allergy': 'screen-options',
    'screen-payment': 'screen-allergy',
  };
  function goBack() {
    if (typeof showScreen !== 'function' || typeof currentScreen === 'undefined') {
      console.warn('[intent] showScreen/currentScreen 전역에 없음');
      return;
    }
    const from = currentScreen;
    const dest = BACK_MAP[from];
    if (!dest) {
      console.log(`[intent] back: "${from}" 에서 갈 곳 없음`);
      return;
    }
    showScreen(dest);
    console.log(`[intent] back: ${from} → ${dest}`);
  }

  function selectAllergy(allergens) {
    const name = (allergens || [])[0];
    if (!name) {
      console.warn('[intent] allergy_select 인데 allergens 비어있음');
      return;
    }
    if (typeof showAllergyWarning !== 'function' || !Array.isArray(ALLERGY_INFO)) {
      console.warn('[intent] showAllergyWarning/ALLERGY_INFO 전역에 없음');
      return;
    }
    const match = ALLERGY_INFO.find((a) => a.name === name);
    if (!match) {
      console.warn(`[intent] 알러지 매칭 실패: "${name}"`);
      return;
    }
    showAllergyWarning(match.name);
    console.log(`[intent] allergy_select: ${match.name}`);
  }

  window.handleIntent = function handleIntent(intent) {
    if (!intent || !intent.intent) {
      console.warn('[intent] invalid payload', intent);
      return;
    }
    console.log(`[intent] ${intent.intent} → "${intent.response_text || ''}"`);
    switch (intent.intent) {
      case 'add_menu':
        addItems(intent.items || []);
        break;
      case 'set_option':
        applyOptions(intent.items || []);
        break;
      case 'confirm_order':
        if (typeof goToConfirm === 'function') goToConfirm();
        else console.warn('[intent] goToConfirm 전역에 없음');
        break;
      case 'back':
        goBack();
        break;
      case 'allergy_select':
        selectAllergy(intent.allergens || []);
        break;
      case 'allergy_confirm':
        if (typeof goToPayment === 'function') goToPayment();
        else console.warn('[intent] goToPayment 전역에 없음');
        break;
      case 'unknown':
        break;
      default:
        console.log(`[intent] "${intent.intent}" 은 아직 미구현`);
    }
  };
})();

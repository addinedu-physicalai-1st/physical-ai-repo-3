// LLM intent 응답을 키오스크 UI 액션으로 매핑.
// Phase 2 검증 범위는 add_menu 만. 나머지 intent 는 Phase 3+ 에서 확장.
(() => {
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
      case 'allergy_select':
        selectAllergy(intent.allergens || []);
        break;
      case 'unknown':
        break;
      default:
        console.log(`[intent] "${intent.intent}" 은 Phase 2 범위 밖 — 아직 미구현`);
    }
  };
})();

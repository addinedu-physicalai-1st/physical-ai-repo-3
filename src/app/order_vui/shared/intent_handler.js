// LLM intent 응답을 키오스크 UI 액션으로 매핑.
(() => {
  const isTable = () => window.VOICE_MODE === 'table';

  // LLM 영문 enum → kiosk.html 옵션 한글 라벨
  const SHOT_MAP = { extra: '추가', less: '기본' };
  const ICE_MAP = { less: '얼음 없음', more: '각 얼음' };

  // 메뉴 매칭: 정식 이름 + 별명(aliases) 모두 비교. 공백/대소문자 무시.
  // LLM 이 menu_name 을 "아메리카노"(별명) 로 줘도 name="coffee" 항목을 찾도록.
  function normalizeName(s) {
    return String(s == null ? '' : s).toLowerCase().replace(/\s+/g, '');
  }
  function findMenu(name) {
    if (!name || !Array.isArray(MENU)) return null;
    const q = normalizeName(name);
    if (!q) return null;
    const candsOf = (m) => [m.name, ...(Array.isArray(m.aliases) ? m.aliases : [])];
    // 1) 정확 매칭 (이름/별명)
    const exact = MENU.find((m) => candsOf(m).some((c) => normalizeName(c) === q));
    if (exact) return exact;
    // 2) 부분 매칭: 이름/별명이 발화 안에 포함 (예: "아메리카노 한잔" → "아메리카노")
    const partial = MENU.find((m) =>
      candsOf(m).some((c) => {
        const n = normalizeName(c);
        return n.length >= 2 && q.includes(n);
      }),
    );
    return partial || null;
  }

  function addItems(items) {
    if (typeof addToCart !== 'function' || !Array.isArray(MENU)) {
      console.warn('[intent] addToCart/MENU 가 전역에 없음 — kiosk 컨텍스트가 아닙니다.');
      return;
    }
    for (const it of items || []) {
      const name = it && it.menu_name;
      if (!name) continue;
      const menu = findMenu(name);
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
        const menu = findMenu(it.menu_name);
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

  window.handleIntent = async function handleIntent(intent, asrText) {
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
      case 'confirm_order': {
        // "주문 확인 / 다음 / 다음으로" 류 발화. 현재 화면 기준 다음 단계로 진행.
        // table 모드: 결제 화면이 없어 알러지 다음은 카운터 안내 (submitTableOrder).
        const NEXT_STEP = isTable()
          ? {
              'screen-menu': 'goToConfirm',
              'screen-confirm': 'goToOptions',
              'screen-options': 'goToAllergy',
              'screen-allergy': 'submitTableOrder',
            }
          : {
              'screen-menu': 'goToConfirm',
              'screen-confirm': 'goToOptions',
              'screen-options': 'goToAllergy',
              'screen-allergy': 'goToPayment',
            };
        const fn = (typeof currentScreen !== 'undefined') ? NEXT_STEP[currentScreen] : null;
        if (fn && typeof window[fn] === 'function') {
          window[fn]();
          console.log(`[intent] confirm_order: ${fn}() (from ${currentScreen})`);
        } else {
          console.log(`[intent] confirm_order: "${currentScreen}" 에서 다음 단계 없음`);
        }
        break;
      }
      case 'back':
        goBack();
        break;
      case 'allergy_select':
        selectAllergy(intent.allergens || []);
        break;
      case 'allergy_confirm':
        if (isTable()) {
          if (typeof window.submitTableOrder === 'function') window.submitTableOrder();
          else console.warn('[intent] submitTableOrder 전역에 없음 (table 모드)');
        } else if (typeof goToPayment === 'function') {
          goToPayment();
        } else {
          console.warn('[intent] goToPayment 전역에 없음');
        }
        break;
      case 'checkout': {
        // 이중 확인 게이트: LLM 이 checkout 으로 분류해도 룰 매처가 동의해야 진행.
        if (typeof window.isCheckout !== 'function') {
          console.warn('[intent] isCheckout 미정의 — checkout_rules.js 누락?');
          break;
        }
        const rule = window.isCheckout(asrText);
        if (!rule.matched) {
          // LLM 만 결제로 분류, 룰은 차단 → 사용자 재확인. intent.response_text 를 차단 멘트로 덮어써서
          // voice.js processUtterance 가 일관되게 TTS 로 흘리도록 한다.
          console.warn(`[intent] checkout 차단 (rule:${rule.reason}, asr:"${asrText}") — 재확인 멘트 송출`);
          intent.response_text = isTable()
            ? '주문을 카운터로 전달할까요? 주문 확인 이라고 말씀해 주세요'
            : '결제를 진행할까요? 카드로 결제할게 라고 말씀해 주세요';
          break;
        }
        if (isTable()) {
          // table 모드: 결제는 카운터에서. 룰 통과 시 그대로 주문 제출.
          console.log(`[intent] checkout (table): submitTableOrder (rule:${rule.reason})`);
          if (typeof window.submitTableOrder === 'function') window.submitTableOrder();
          else console.warn('[intent] submitTableOrder 전역 없음 (table 모드)');
          break;
        }
        const method = intent.payment_method || 'card';
        if (typeof selectedPayment === 'undefined') {
          console.warn('[intent] selectedPayment 전역 없음');
          break;
        }
        selectedPayment = method;
        if (typeof showScreen === 'function') showScreen('screen-payment');
        console.log(`[intent] checkout: method=${method} (rule:${rule.reason})`);
        if (typeof processPayment === 'function') setTimeout(() => processPayment(), 300);
        else console.warn('[intent] processPayment 전역 없음');
        break;
      }
      case 'unknown':
        break;
      default:
        console.log(`[intent] "${intent.intent}" 은 아직 미구현`);
    }
  };
})();

// 결제 의도 룰 매처. LLM intent==='checkout' 과 별개로 ASR 원문에서
// 결제 키워드를 직접 찾아 양쪽이 모두 동의할 때만 결제 진행 (이중 확인 게이트).
// base: PoC p4_checkout/rule_matcher_prototype.py
(() => {
  const CHECKOUT_PATTERNS = [
    '결제', '계산', '주문 끝', '이걸로 끝', '그만 시',
    '여기까지', '끝났', '끝낼', 'pay',
  ];
  // 결제 단어 앞에 붙어 의도를 뒤집는 표현. 하나라도 들어 있으면 즉시 차단.
  const NEGATIVE_WORDS = ['안 ', '말고', '취소', '아직', '잠깐'];

  window.isCheckout = function isCheckout(text) {
    const n = (text || '').toLowerCase().trim();
    for (const neg of NEGATIVE_WORDS) {
      if (n.includes(neg)) return { matched: false, reason: `negative:${neg.trim()}` };
    }
    for (const p of CHECKOUT_PATTERNS) {
      if (n.includes(p.toLowerCase())) return { matched: true, reason: `matched:${p}` };
    }
    return { matched: false, reason: 'no-match' };
  };
})();

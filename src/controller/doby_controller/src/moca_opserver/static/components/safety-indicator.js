/* safety-indicator.js — 헤더 운영 상태 (NORMAL / ALARM / BATT LOW). DOM 부분 갱신.
 *
 * OFFLINE 표시는 Doby/DDooby <robot-status> 컴포넌트가 담당 (중복 회피).
 * 본 컴포넌트는 운영 안전 + 배터리만 표시.
 *
 * 우선순위: ALARM > BATT LOW > NORMAL (안전이 가장 critical).
 *   - mode.safety_ok=false → ALARM (emergency / rapport_abort / zone 통합)
 *   - mode.battery_ok=false → BATT LOW
 *   - 둘 다 true (또는 unknown 안전 측 허용) → NORMAL
 */

class SafetyIndicator extends HTMLElement {
  connectedCallback() {
    this._lastState = null;
    this._build();
    if (window.store) {
      window.store.on('mode', () => this._refresh());
    }
    this._refresh();
  }

  _build() {
    this.innerHTML = `
      <span class="safety safety--normal">
        <span class="safety__dot" aria-hidden="true"></span>
        <span class="safety__text">NORMAL</span>
      </span>
    `;
    this._span = this.querySelector('.safety');
    this._text = this.querySelector('.safety__text');
  }

  _computeState() {
    const mode = (window.store && window.store.get('mode')) || null;
    // unknown (null/undefined) 은 안전 측 허용 → true 로 간주 (NORMAL 표시).
    const safetyOk = !mode || mode.safety_ok !== false;
    const batteryOk = !mode || mode.battery_ok !== false;
    if (!safetyOk)  return { label: 'ALARM',    cls: 'alarm' };
    if (!batteryOk) return { label: 'BATT LOW', cls: 'batt-low' };
    return { label: 'NORMAL', cls: 'normal' };
  }

  _refresh() {
    const s = this._computeState();
    const key = `${s.cls}:${s.label}`;
    if (key === this._lastState) return;
    this._lastState = key;
    this._span.className = `safety safety--${s.cls}`;
    this._text.textContent = s.label;
  }
}

customElements.define('safety-indicator', SafetyIndicator);

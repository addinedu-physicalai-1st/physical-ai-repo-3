/* battery-gauge.js — 배터리 % 게이지 web component (DOM 부분 갱신).
 *
 * 사용:  <battery-gauge></battery-gauge>
 */

class BatteryGauge extends HTMLElement {
  connectedCallback() {
    this._lastLevel = null;
    this._lastText = null;
    this._build();
    if (window.store) {
      window.store.on('battery', (b) => this._update(b));
    }
  }

  _build() {
    this.innerHTML = `
      <div class="gauge" data-level="unknown" aria-label="배터리">
        <span class="gauge__label">BATT</span>
        <div class="gauge__bar">
          <div class="gauge__fill" style="width:0%"></div>
        </div>
        <span class="gauge__text">—</span>
      </div>
    `;
    this._gauge = this.querySelector('.gauge');
    this._fill = this.querySelector('.gauge__fill');
    this._text = this.querySelector('.gauge__text');
  }

  _level(pct) {
    if (pct === null || pct === undefined || pct < 0) return 'unknown';
    if (pct < 0.20) return 'critical';
    if (pct < 0.30) return 'low';
    return 'ok';
  }

  _update(batt) {
    const pct = (batt && typeof batt.percentage === 'number') ? batt.percentage : null;
    const level = this._level(pct);
    const text = (pct === null || pct < 0) ? '—' : `${Math.round(pct * 100)}%`;
    if (level !== this._lastLevel) {
      this._gauge.setAttribute('data-level', level);
      this._lastLevel = level;
    }
    if (text !== this._lastText) {
      this._text.textContent = text;
      this._fill.style.width = (pct === null || pct < 0) ? '0%' : `${Math.round(pct * 100)}%`;
      this._gauge.setAttribute('aria-label', `배터리 ${text}`);
      this._lastText = text;
    }
  }
}

customElements.define('battery-gauge', BatteryGauge);

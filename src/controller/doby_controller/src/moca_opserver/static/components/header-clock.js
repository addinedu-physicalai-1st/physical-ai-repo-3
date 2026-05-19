/* header-clock.js — 현재 시각 1Hz 갱신 */

class HeaderClock extends HTMLElement {
  connectedCallback() {
    this._render();
    this._timer = setInterval(() => this._render(), 1000);
  }
  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }
  _render() {
    const now = new Date();
    const Y = now.getFullYear();
    const M = String(now.getMonth() + 1).padStart(2, '0');
    const D = String(now.getDate()).padStart(2, '0');
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    this.textContent = `${Y}-${M}-${D} ${hh}:${mm}:${ss}`;
  }
}

customElements.define('header-clock', HeaderClock);

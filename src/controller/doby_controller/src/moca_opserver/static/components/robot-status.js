/* robot-status.js — 헤더 안 로봇 (Doby / DDoby) Online/Offline 표시.
 *
 * 사용:
 *   <robot-status name="Doby" store-key="online"></robot-status>     <!-- Vic Pinky -->
 *   <robot-status name="DDoby"></robot-status>                         <!-- OpenARM, 정적 offline (미연동) -->
 *
 * store-key 가 있으면 store.on(key) 로 동적 갱신.
 * 없으면 정적 offline (아직 백엔드 wiring 없음 — 추후 연결).
 */

class RobotStatus extends HTMLElement {
  static get observedAttributes() { return ['name', 'store-key']; }

  connectedCallback() {
    this._name = this.getAttribute('name') || 'Robot';
    this._key = this.getAttribute('store-key') || null;
    this._lastKey = null;
    this._build();
    if (window.store && this._key) {
      window.store.on(this._key, () => this._refresh());
    }
    this._refresh();
  }

  _build() {
    this.innerHTML = `
      <span class="robot-status robot-status--offline">
        <span class="robot-status__dot" aria-hidden="true"></span>
        <span class="robot-status__text">${this._name} Offline</span>
      </span>
    `;
    this._span = this.querySelector('.robot-status');
    this._text = this.querySelector('.robot-status__text');
  }

  _refresh() {
    const online = this._key
      ? (window.store && window.store.get(this._key) === true)
      : false;
    const cacheKey = `${this._name}:${online}`;
    if (cacheKey === this._lastKey) return;
    this._lastKey = cacheKey;
    this._span.className = `robot-status robot-status--${online ? 'online' : 'offline'}`;
    this._text.textContent = `${this._name} ${online ? 'Online' : 'Offline'}`;
  }
}

customElements.define('robot-status', RobotStatus);

/* mode-badge.js — 현재 모드 표시 web component (spec §11.2)
 *
 * 사용:  <mode-badge></mode-badge>
 * 갱신:  store.on('mode', ...) + store.on('online', ...) 자동 구독.
 *
 * DOM 부분 갱신 — innerHTML 재생성 X (깜박임 방지).
 * 같은 모드 + 같은 entered_at 이면 갱신 skip.
 */

class ModeBadge extends HTMLElement {
  connectedCallback() {
    this._currentMode = null;
    this._currentEnteredAt = null;
    this._isOffline = false;
    this._timer = null;
    this._build();
    if (window.store) {
      window.store.on('mode', (m) => this._onMode(m));
      window.store.on('online', (on) => this._onOnline(on));
    }
    // 1Hz timer — entered 경과 시간 갱신 (모드 자체는 안 바뀌어도)
    this._timer = setInterval(() => this._updateTimeOnly(), 1000);
  }
  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  _build() {
    /* 한 번만 생성 — 이후 부분 갱신만 */
    this.innerHTML = `
      <div class="badge" data-mode="idle" role="status" aria-live="polite">
        <span class="label">CONNECTING</span>
        <span class="time"></span>
      </div>
    `;
    this._badge = this.querySelector('.badge');
    this._label = this.querySelector('.label');
    this._time = this.querySelector('.time');
  }

  _onMode(mode) {
    if (!mode || !mode.current) return;
    // 모드 자체 + entered_at 둘 다 동일 → 갱신 skip (깜박임 방지)
    if (this._currentMode === mode.current &&
        this._currentEnteredAt === mode.entered_at) {
      return;
    }
    this._currentMode = mode.current;
    this._currentEnteredAt = mode.entered_at;
    if (!this._isOffline) {
      this._badge.setAttribute('data-mode', mode.current);
      this._label.textContent = mode.current.toUpperCase();
    }
    this._updateTimeOnly();
  }

  _onOnline(on) {
    const offline = !on;
    if (offline === this._isOffline) return;
    this._isOffline = offline;
    if (offline) {
      this._badge.setAttribute('data-mode', 'offline');
      this._label.textContent = 'OFFLINE';
      this._time.textContent = '';
    } else if (this._currentMode) {
      this._badge.setAttribute('data-mode', this._currentMode);
      this._label.textContent = this._currentMode.toUpperCase();
      this._updateTimeOnly();
    }
  }

  _updateTimeOnly() {
    if (this._isOffline || !this._currentEnteredAt) {
      this._time.textContent = '';
      return;
    }
    const t = window.utils ? window.utils.formatTime(this._currentEnteredAt) : '';
    if (this._time.textContent !== t) {
      this._time.textContent = t;
    }
  }
}

customElements.define('mode-badge', ModeBadge);

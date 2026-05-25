/* event-feed.js — 실시간 이벤트 피드 (spec §4.2, §7)
 *
 * 사용:  <event-feed max="10"></event-feed>
 * 갱신:  store.on('events', ...)  store.events 는 ring buffer (최근 200건, 신규 unshift)
 *
 * 레벨 아이콘 (spec §7.4): info ℹ / warn ⚠ / error ❌
 */

const LEVEL_LABELS = { info: 'INFO', warn: 'WARN', error: 'ERR' };
const LEVEL_CLASSES = { info: 'feed-info', warn: 'feed-warn', error: 'feed-error' };

class EventFeed extends HTMLElement {
  connectedCallback() {
    const max = parseInt(this.getAttribute('max') || '15', 10);
    this._max = isFinite(max) ? max : 15;
    this._render([]);
    if (window.store) window.store.on('events', (evts) => this._render(evts || []));
  }

  _render(events) {
    const top = events.slice(0, this._max);
    if (top.length === 0) {
      this.innerHTML = `
        <div class="feed">
          <div class="feed__empty">이벤트 수신 대기…</div>
        </div>
      `;
      return;
    }
    const rows = top.map(e => this._row(e)).join('');
    this.innerHTML = `<div class="feed">${rows}</div>`;
  }

  _row(e) {
    const lvl = (e.level || 'info').toLowerCase();
    const label = LEVEL_LABELS[lvl] || 'INFO';
    const cls = LEVEL_CLASSES[lvl] || 'feed-info';
    const time = window.utils ? window.utils.formatTime(e.ts) : '';
    const src = e.source || '';
    const msg = (e.msg || '').replace(/[<>]/g, c => c === '<' ? '&lt;' : '&gt;');
    return `
      <div class="feed__row ${cls}">
        <span class="feed__time">${time}</span>
        <span class="feed__level">${label}</span>
        <span class="feed__source">${src}</span>
        <span class="feed__msg">${msg}</span>
      </div>
    `;
  }
}

customElements.define('event-feed', EventFeed);

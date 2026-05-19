/* table-card.js — 단일 테이블 occupancy 카드 (spec §6)
 *
 * 사용:  <table-card table-id="T01"></table-card>
 * 갱신:  store.on('tables', ...)  store.tables[table_id] 변화 시
 */

const OCCUPANCY_META = {
  empty:    { label: '비어있음',   cls: 'occ-empty' },
  occupied: { label: '점유',        cls: 'occ-occupied' },
  finished: { label: '식사 완료',   cls: 'occ-finished' },
  unknown:  { label: '미확인',      cls: 'occ-unknown' },
};

class TableCard extends HTMLElement {
  static get observedAttributes() { return ['table-id']; }
  connectedCallback() {
    this._tableId = this.getAttribute('table-id') || '';
    this._render(null);
    if (window.store) window.store.on('tables', (t) => this._render((t || {})[this._tableId]));
  }

  _render(data) {
    const tid = this._tableId;
    const meta = OCCUPANCY_META[(data && data.occupancy) || 'unknown'] || OCCUPANCY_META.unknown;
    const persons = (data && typeof data.person_count === 'number') ? data.person_count : 0;
    const conf = (data && typeof data.confidence === 'number') ? Math.round(data.confidence * 100) : 0;
    const last = (data && data.last_update) ? utils.formatTime(data.last_update) : '—';
    const subLabel = (data && data.occupancy === 'occupied' && persons > 0)
      ? `${meta.label} (${persons}명)` : meta.label;

    this.innerHTML = `
      <div class="tcard ${meta.cls}" data-table="${tid}">
        <div class="tcard__hdr">
          <span class="tcard__id">${tid}</span>
          <span class="tcard__dot" aria-hidden="true"></span>
        </div>
        <div class="tcard__status">${subLabel}</div>
        <div class="tcard__meta">
          신뢰도: ${conf}% · 갱신: ${last}
        </div>
      </div>
    `;
  }
}

customElements.define('table-card', TableCard);

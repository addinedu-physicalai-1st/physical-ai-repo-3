/* engagement-timeline.js — Track C 시계열 그래프 web component
 *
 * V / A / engagement_score 3 라인 + rapport event 마커.
 * X 0~60s, Y -1~+1. native SVG (Chart.js 미사용).
 *
 * 사용: <engagement-timeline></engagement-timeline>
 *      const el = document.querySelector('engagement-timeline');
 *      el.render(wsPayload);
 *
 * spec: docs/superpowers/specs/2026-05-21-engagement-timeline-design.md §6
 */
class EngagementTimeline extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <svg class="engagement-timeline" viewBox="0 0 600 220"
           preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
        <line class="et-axis" x1="0" y1="100" x2="600" y2="100"></line>
        <line class="et-grid" x1="0" y1="0" x2="600" y2="0"></line>
        <line class="et-grid" x1="0" y1="200" x2="600" y2="200"></line>
        <line class="et-grid" x1="0" y1="50" x2="600" y2="50"></line>
        <line class="et-grid" x1="0" y1="150" x2="600" y2="150"></line>

        <text class="et-legend" x="5" y="12">+1</text>
        <text class="et-legend" x="5" y="105">0</text>
        <text class="et-legend" x="5" y="198">-1</text>
        <text class="et-legend" x="0" y="215">60s</text>
        <text class="et-legend" x="290" y="215">30s</text>
        <text class="et-legend" x="570" y="215">now</text>

        <polyline class="et-line-v" id="et-line-v" points=""></polyline>
        <polyline class="et-line-a" id="et-line-a" points=""></polyline>
        <polyline class="et-line-score" id="et-line-score" points=""></polyline>
        <g id="et-markers"></g>

        <g class="et-legend-row">
          <line class="et-line-v" x1="450" y1="8" x2="458" y2="8"></line>
          <text class="et-legend" x="463" y="11">V</text>
          <line class="et-line-a" x1="485" y1="8" x2="493" y2="8"></line>
          <text class="et-legend" x="498" y="11">A</text>
          <line class="et-line-score" x1="520" y1="8" x2="528" y2="8"></line>
          <text class="et-legend" x="533" y="11">score</text>
        </g>
      </svg>
    `;
    this._lineV = this.querySelector('#et-line-v');
    this._lineA = this.querySelector('#et-line-a');
    this._lineScore = this.querySelector('#et-line-score');
    this._markers = this.querySelector('#et-markers');
  }

  /**
   * WS /ws/v1/engaging payload 받아서 SVG 갱신.
   * payload = {emotion: {trajectory: [{t, v, a, conf}]}, engagement: {score_history: [{ts, score}], rapport_markers: [{ts, type, weight}]}}
   */
  render(payload) {
    if (!payload || !this._lineV) return;

    const traj = (payload.emotion && payload.emotion.trajectory) || [];
    const scoreHistory = (payload.engagement && payload.engagement.score_history) || [];
    const markers = (payload.engagement && payload.engagement.rapport_markers) || [];

    let now = 0;
    if (traj.length) now = traj[traj.length - 1].t;
    else if (scoreHistory.length) now = scoreHistory[scoreHistory.length - 1].ts;

    if (!now) {
      this._clear();
      return;
    }
    const start = now - 60.0;

    const tx = (ts) => Math.max(0, Math.min(600, ((ts - start) / 60.0) * 600));
    const ty = (val) => 100 - Math.max(-1, Math.min(1, val)) * 100;

    this._lineV.setAttribute('points',
      traj
        .filter(p => p.t >= start)
        .map(p => `${tx(p.t).toFixed(1)},${ty(p.v).toFixed(1)}`)
        .join(' '));
    this._lineA.setAttribute('points',
      traj
        .filter(p => p.t >= start)
        .map(p => `${tx(p.t).toFixed(1)},${ty(p.a).toFixed(1)}`)
        .join(' '));
    this._lineScore.setAttribute('points',
      scoreHistory
        .filter(p => p.ts >= start)
        .map(p => `${tx(p.ts).toFixed(1)},${ty(p.score).toFixed(1)}`)
        .join(' '));

    const cls = {
      engagement_up: 'et-marker-up',
      engagement_down: 'et-marker-down',
      abort_trigger: 'et-marker-abort',
    };
    this._markers.innerHTML = markers
      .filter(m => m.ts >= start)
      .map(m => `<circle class="${cls[m.type] || ''}" cx="${tx(m.ts).toFixed(1)}" cy="${ty(m.weight).toFixed(1)}" r="3"></circle>`)
      .join('');
  }

  _clear() {
    if (!this._lineV) return;
    this._lineV.setAttribute('points', '');
    this._lineA.setAttribute('points', '');
    this._lineScore.setAttribute('points', '');
    this._markers.innerHTML = '';
  }
}

customElements.define('engagement-timeline', EngagementTimeline);

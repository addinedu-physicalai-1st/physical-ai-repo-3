/* engaging-analytics.js — engaging 모드 라이브 분석 패널
 *
 * operator.html (localhost:8765) 의 V/A circumplex + rapport list + minigame card
 * + 강제 발화 form 을 M3 dashboard modes.html 의 expand 섹션으로 포팅.
 *
 * 데이터 채널: WS /ws/v1/engaging (5Hz throttle, opserver 가 broadcast).
 * payload: {ts, emotion: {latest, trajectory}, rapport: {counters, recent},
 *           minigame: {latest, recent}, mode: {current, entered_at}}.
 *
 * mode 진입/이탈에 따라 섹션 show/hide + WS 연결 토글.
 */
(function () {
  const VTHR = 0.15;   // |V| < VTHR → 중립 색상
  const TRAJ_MAX = 30; // SVG 궤적 포인트 수

  function $(id) { return document.getElementById(id); }
  function colorVal(v) {
    if (v > VTHR) return 'v-pos';
    if (v < -VTHR) return 'v-neg';
    return 'v-mid';
  }

  function renderCustomerLabel(latest) {
    const el = $('ea-customer');
    if (!el) return;
    if (!latest) {
      el.textContent = '— 손님 대기 중';
      el.classList.add('unknown');
      return;
    }
    const tid = latest.track_id;
    const gid = latest.group_id;
    if (tid === undefined || tid < 0) {
      el.textContent = '— 손님 인식 X';
      el.classList.add('unknown');
    } else {
      const group = (gid === undefined || gid < 0) ? 'Solo' : `Group #${gid}`;
      el.textContent = `🎯 Customer #${tid} · ${group}`;
      el.classList.remove('unknown');
    }
  }

  function renderEmotion(emo) {
    const trajEl = $('ea-traj');
    if (!emo || !emo.latest) {
      $('ea-v').textContent = '—';
      $('ea-a').textContent = '—';
      $('ea-conf').textContent = '—';
      $('ea-conf-bar').style.width = '0%';
      $('ea-flags').textContent = '—';
      $('ea-source').textContent = '—';
      $('ea-cur').setAttribute('r', '0');
      if (trajEl) trajEl.innerHTML = '';
      renderCustomerLabel(null);
      return;
    }
    const L = emo.latest;
    const vEl = $('ea-v'), aEl = $('ea-a');
    vEl.textContent = (L.v >= 0 ? '+' : '') + L.v.toFixed(2);
    aEl.textContent = (L.a >= 0 ? '+' : '') + L.a.toFixed(2);
    vEl.className = 'ea-big ' + colorVal(L.v);
    aEl.className = 'ea-big ' + colorVal(L.a);
    $('ea-conf').textContent = L.conf.toFixed(2);
    $('ea-conf-bar').style.width = (L.conf * 100).toFixed(0) + '%';
    $('ea-flags').textContent =
      (L.flags && L.flags.length) ? L.flags.join(', ') : '(없음)';
    $('ea-source').textContent = L.source || '—';

    const cx = Math.max(-100, Math.min(100, L.v * 100));
    const cy = Math.max(-100, Math.min(100, -L.a * 100));
    const cur = $('ea-cur');
    cur.setAttribute('cx', cx);
    cur.setAttribute('cy', cy);
    cur.setAttribute('r', 4);

    const pts = (emo.trajectory || []).slice(-TRAJ_MAX);
    let svg = '';
    pts.forEach((p, i) => {
      const x = Math.max(-100, Math.min(100, p.v * 100));
      const y = Math.max(-100, Math.min(100, -p.a * 100));
      const op = ((i + 1) / pts.length) * 0.6;
      const r = 1.2 + (i / pts.length) * 1.0;
      svg += `<circle class="traj-pt" cx="${x}" cy="${y}" r="${r}" `
          + `fill="var(--pink-soft)" opacity="${op.toFixed(2)}"></circle>`;
    });
    if (trajEl) trajEl.innerHTML = svg;
    renderCustomerLabel(emo.latest);
  }

  function renderRapport(rap) {
    if (!rap) return;
    const c = rap.counters || {};
    $('ea-rap-up').textContent = c.engagement_up || 0;
    $('ea-rap-down').textContent = c.engagement_down || 0;
    $('ea-rap-abort').textContent = c.abort_trigger || 0;
    $('ea-rap-neut').textContent = c.neutral_continue || 0;

    const recEl = $('ea-rap-recent');
    const recent = (rap.recent || []).slice(-8).reverse();
    if (!recent.length) {
      recEl.innerHTML = '<div class="ev-neut">(아직 이벤트 없음)</div>';
      return;
    }
    const cls = {
      engagement_up: 'ev-up', engagement_down: 'ev-down',
      abort_trigger: 'ev-abrt', neutral_continue: 'ev-neut',
    };
    recEl.innerHTML = recent.map(r => {
      const t = new Date(r.ts * 1000).toLocaleTimeString('ko-KR');
      const w = (r.weight >= 0 ? '+' : '') + r.weight.toFixed(2);
      const tag = (r.track_id !== undefined && r.track_id >= 0)
        ? `[#${r.track_id}] ` : '';
      return `<div class="${cls[r.type] || ''}">[${t}] ${tag}${r.type} `
           + `w=${w} V=${r.v.toFixed(2)} A=${r.a.toFixed(2)} `
           + `· ${r.reason || ''}</div>`;
    }).join('');
  }

  function renderMinigame(mg) {
    if (!mg) return;
    const recEl = $('ea-mg-recent');
    const recent = (mg.recent || []).slice(-5).reverse();
    if (!recent.length) {
      recEl.innerHTML = '<div class="muted">(아직 결과 없음)</div>';
      return;
    }
    recEl.innerHTML = recent.map(r => {
      const t = new Date(r.ts * 1000).toLocaleTimeString('ko-KR');
      const cw = r.customer_wins, rw = r.robot_wins;
      const result = cw > rw
        ? `<span class="win">고객승</span>`
        : (cw < rw ? `<span class="lose">로봇승</span>`
                   : `<span class="lose">무승부</span>`);
      const score = `${cw}:${rw}` + (r.ties ? ` (${r.ties}무)` : '');
      return `<div class="mg-row">`
           + `<span class="game">[${t}] ${r.game_id}</span>`
           + `<span class="score">${score} rate=${r.customer_win_rate.toFixed(2)} `
           + `${r.duration_sec.toFixed(1)}s ${r.completed ? '✓' : '×'} ${result}`
           + `</span></div>`;
    }).join('');
  }

  class EngagingWS {
    constructor() {
      this.ws = null;
      this.retryDelay = 1000;
      this.maxRetry = 15000;
      this.want = false;       // show 상태 = 연결 의도
      this.retryTimer = null;
    }
    open() {
      this.want = true;
      if (this.ws) return;
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${location.host}/ws/v1/engaging`;
      try { this.ws = new WebSocket(url); }
      catch (e) { console.error('[engaging-ws] construct', e); this._scheduleRetry(); return; }
      this.ws.onopen = () => {
        this.retryDelay = 1000;
      };
      this.ws.onmessage = (e) => {
        try {
          const j = JSON.parse(e.data);
          renderEmotion(j.emotion);
          renderRapport(j.rapport);
          renderMinigame(j.minigame);
        } catch (err) { /* ignore */ }
      };
      this.ws.onclose = () => {
        this.ws = null;
        if (this.want) this._scheduleRetry();
      };
      this.ws.onerror = () => { /* onclose 가 처리 */ };
    }
    close() {
      this.want = false;
      if (this.retryTimer) { clearTimeout(this.retryTimer); this.retryTimer = null; }
      if (this.ws) {
        try { this.ws.close(); } catch (e) {}
        this.ws = null;
      }
    }
    _scheduleRetry() {
      if (this.retryTimer) return;
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        if (this.want) this.open();
      }, this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, this.maxRetry);
    }
  }

  function bindUtter() {
    const btn = $('ea-utter-send');
    if (btn) {
      btn.addEventListener('click', () => {
        const text = ($('ea-utter-text').value || '').trim();
        if (!text) {
          if (window.toast) toast('발화 텍스트 비어있음', 'warn');
          return;
        }
        const persona = ($('ea-utter-persona').value || '').trim();
        const face = ($('ea-utter-face').value || '').trim();
        api.post('/dialog/utter', { text, persona, face_expression: face })
          .then(() => {
            if (window.toast) toast(`발화 전송: "${text.slice(0, 24)}"`, 'info');
            $('ea-utter-text').value = '';
          })
          .catch((e) => {
            if (window.toast) toast(`발화 실패 (${e.status || 'NET'})`, 'error');
          });
      });
    }
    // 표정만 적용 — REST POST /api/v1/command (command_type='express')
    const btnExp = $('ea-expression-apply');
    if (btnExp) {
      btnExp.addEventListener('click', () => {
        const exp = ($('ea-utter-face').value || '').trim();
        if (!exp) {
          if (window.toast) toast('표정 미선택', 'warn');
          return;
        }
        api.post('/command', {
          command_type: 'express',
          payload: { face_expression: exp },
        }).then(() => {
          if (window.toast) toast(`표정 ${exp} 적용 요청 전송`, 'info');
        }).catch((e) => {
          if (window.toast) toast(`표정 적용 실패 (${e.status || 'NET'})`, 'error');
        });
      });
    }
  }

  function init() {
    const section = $('engaging-analytics');
    if (!section) return;   // 다른 페이지에 로드된 경우
    const ws = new EngagingWS();
    function apply(mode) {
      const cur = (mode && mode.current) || 'idle';
      if (cur === 'engaging') {
        section.hidden = false;
        ws.open();
      } else {
        section.hidden = true;
        ws.close();
      }
    }
    if (window.store) {
      store.on('mode', apply);
      apply(store.get('mode'));
    }
    bindUtter();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

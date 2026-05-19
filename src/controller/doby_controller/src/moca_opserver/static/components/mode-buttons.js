/* mode-buttons.js — 5 빠른 모드 버튼 + STOP (spec §4.4)
 *
 * 사용:  <mode-buttons></mode-buttons>
 * 동작:
 *   - 5 모드 클릭 → 확인 모달 → WS send {type:'set_mode', mode, params, override_priority}
 *   - STOP → 확인 모달 → WS send {type:'emergency_stop'}
 *   - 활동 모드 (serving/guiding) 는 운영자 클릭이라 override_priority=true (점주 의도 우선)
 *   - serving/guiding 은 TableSelectModal, engaging 은 PersonaModal (M1 stretch — 본 단계는 단순 confirm)
 */

const MODE_LABELS = [
  { id: 'idle',     label: '대기',  desc: 'home_pose 정차' },
  { id: 'serving',  label: '서빙',  desc: '테이블 배달', needsTable: true },
  { id: 'patrol',   label: '순회',  desc: '5 테이블 1회 patrol' },
  { id: 'guiding',  label: '안내',  desc: '카운터→빈테이블', needsTable: true },
  { id: 'engaging', label: '모객',  desc: '빈 테이블 50% 이상 시,<br>모객 시작', needsPersona: true },
];

const TABLES = ['T01', 'T02', 'T03', 'T04', 'T05'];
const PERSONAS = ['casual_browser', 'friendly_child', 'professional_adult'];

class ModeButtons extends HTMLElement {
  connectedCallback() {
    this._render();
  }

  _render() {
    const buttons = MODE_LABELS.map(m =>
      `<button class="mode-button" data-mode="${m.id}" aria-label="${m.id} 모드 진입">
         <span class="mode-button__label">${m.label}</span>
         <span class="mode-button__desc">${m.desc}</span>
       </button>`).join('');

    this.innerHTML = `
      <div class="mode-buttons">${buttons}</div>
      <button class="mode-button mode-button--stop" id="btn-emergency-stop"
              aria-label="비상정지">STOP</button>
    `;

    this.querySelectorAll('.mode-button[data-mode]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const mode = btn.getAttribute('data-mode');
        this._onModeClick(mode);
      });
    });
    this.querySelector('#btn-emergency-stop').addEventListener('click', () => {
      this._onEmergencyStop();
    });
  }

  async _onModeClick(modeId) {
    const meta = MODE_LABELS.find(m => m.id === modeId);
    if (!meta) return;

    // serving/guiding — 테이블 선택 모달
    let params = {};
    if (meta.needsTable) {
      const table = await this._pickTable(modeId);
      if (!table) return;
      if (modeId === 'serving') {
        params = { waypoint: table, via_pickup: true };
      } else {
        params = { target_table: table, customer_id: `C-${Date.now()}` };
      }
    } else if (meta.needsPersona) {
      const persona = await this._pickPersona();
      if (!persona) return;
      params = { persona };
    } else {
      const ok = await this._confirm(`${meta.label} 모드로 전환하시겠습니까?`);
      if (!ok) return;
    }

    // WS send
    const ok = window.wsClient && wsClient.send({
      type: 'set_mode',
      mode: modeId,
      params,
      override_priority: true,    // 운영자 의도 우선
    });
    if (ok) {
      this._toast(`${meta.label} 모드 요청 전송됨`, 'info');
    } else {
      this._toast('WebSocket 연결 끊김 — 잠시 후 재시도', 'warn');
    }
  }

  async _onEmergencyStop() {
    const ok = await this._confirm(
      '🛑 비상정지하시겠습니까?\n\n로봇이 즉시 멈추고 5초간 모드 진입 차단됩니다.');
    if (!ok) return;
    const sent = window.wsClient && wsClient.send({ type: 'emergency_stop' });
    if (sent) {
      this._toast('비상정지 명령 전송됨', 'warn');
    } else {
      this._toast('WebSocket 연결 끊김 — 잠시 후 재시도', 'warn');
    }
  }

  // ───── 모달 헬퍼 (M1 단순 prompt/confirm — M3에서 Modal 컴포넌트로 교체) ─────

  _confirm(message) {
    return new Promise(resolve => {
      // 간단한 native confirm — M3 에서 정식 Modal 컴포넌트 도입
      resolve(window.confirm(message));
    });
  }

  _pickTable(modeId) {
    return new Promise(resolve => {
      const msg = `${modeId === 'serving' ? '서빙' : '안내'} 대상 테이블을 입력하세요\n(T01~T05)`;
      const v = window.prompt(msg, 'T01');
      if (!v) return resolve(null);
      const up = String(v).trim().toUpperCase();
      if (!TABLES.includes(up)) {
        this._toast(`잘못된 테이블: ${v} (T01~T05 만)`, 'warn');
        return resolve(null);
      }
      resolve(up);
    });
  }

  _pickPersona() {
    return new Promise(resolve => {
      const msg = `페르소나를 선택하세요:\n${PERSONAS.map((p,i)=>`${i+1}) ${p}`).join('\n')}`;
      const v = window.prompt(msg, '1');
      if (!v) return resolve(null);
      const idx = parseInt(v, 10) - 1;
      if (idx >= 0 && idx < PERSONAS.length) {
        resolve(PERSONAS[idx]);
      } else if (PERSONAS.includes(v)) {
        resolve(v);
      } else {
        this._toast(`잘못된 페르소나: ${v}`, 'warn');
        resolve(null);
      }
    });
  }

  _toast(message, level) {
    // 간이 toast — 우상단 알림. M3 에서 Toast 컴포넌트로 교체.
    const el = document.createElement('div');
    el.className = `toast toast--${level || 'info'}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('toast--show'), 10);
    setTimeout(() => {
      el.classList.remove('toast--show');
      setTimeout(() => el.remove(), 300);
    }, 3000);
  }
}

customElements.define('mode-buttons', ModeButtons);

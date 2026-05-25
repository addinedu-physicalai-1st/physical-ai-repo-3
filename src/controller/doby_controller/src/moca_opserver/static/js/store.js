/* store.js — vanilla pub-sub 상태 관리 (spec §11.2)
 *
 * WSClient 가 받은 메시지를 store 에 반영 → 컴포넌트가 store.on(key, cb) 로 구독.
 */

class Store {
  constructor() {
    this.state = {
      mode: null,           // {current, entered_at, params, battery_ok, safety_ok, last_reject_reason}
      battery: null,        // {percentage, voltage}
      robot_pose: null,     // {x, y, yaw}
      online: false,        // ws + 최근 mode_state 수신
      serving: null,        // serving_progress
      patrol: null,         // patrol_progress
      guiding: null,        // guiding_progress
      tables: {},           // table_id → table data
      events: [],           // event_log ring buffer (최근 200건)
      welcome: null,        // 첫 연결 snapshot
      alarm: null,
    };
    this.subscribers = new Map();   // key → [callback, ...]
    this.MAX_EVENTS = 200;
  }

  set(key, value) {
    this.state[key] = value;
    const subs = this.subscribers.get(key) || [];
    subs.forEach(cb => {
      try { cb(value); } catch (e) { console.error('[store] cb error', e); }
    });
  }

  get(key) { return this.state[key]; }

  on(key, callback) {
    if (!this.subscribers.has(key)) this.subscribers.set(key, []);
    this.subscribers.get(key).push(callback);
    if (this.state[key] !== null && this.state[key] !== undefined) {
      try { callback(this.state[key]); } catch (e) { console.error(e); }
    }
  }
}

window.store = new Store();

// ───── WS 이벤트 → store 갱신 ─────
if (window.wsClient) {
  wsClient.on('welcome', (msg) => {
    store.set('welcome', msg.data);
    const snap = msg.data && msg.data.snapshot;
    if (snap) {
      if (snap.mode) store.set('mode', snap.mode);
      if (snap.battery) store.set('battery', snap.battery);
      if (typeof snap.robot_online === 'boolean') store.set('online', snap.robot_online);
      if (Array.isArray(snap.tables)) {
        const t = {};
        snap.tables.forEach(row => { t[row.id] = row; });
        store.set('tables', t);
      }
    }
  });

  wsClient.on('mode_state', (msg) => {
    store.set('mode', msg.data);
    // robot_online — opserver 의 _tick_robot_online 이 별 alarm 으로 보냄.
    // 본 콜백 수신 자체가 robot_online 활성화 신호.
    store.set('online', true);
  });

  wsClient.on('battery', (msg) => store.set('battery', msg.data));
  wsClient.on('robot_pose', (msg) => store.set('robot_pose', msg.data));
  wsClient.on('serving_progress', (msg) => store.set('serving', msg.data));
  wsClient.on('patrol_progress', (msg) => store.set('patrol', msg.data));
  wsClient.on('guiding_progress', (msg) => store.set('guiding', msg.data));

  wsClient.on('table_update', (msg) => {
    const tables = { ...store.get('tables') };
    if (msg.data && msg.data.table_id) {
      tables[msg.data.table_id] = msg.data;
    }
    store.set('tables', tables);
  });

  wsClient.on('event_log', (msg) => {
    const events = store.get('events').slice();
    events.unshift({ ...msg.data, ts: msg.ts });
    if (events.length > store.MAX_EVENTS) events.pop();
    store.set('events', events);
  });

  wsClient.on('alarm', (msg) => store.set('alarm', msg.data));

  // WS 끊김 시 online=false
  wsClient.on('ws:close', () => store.set('online', false));
  wsClient.on('ws:open', () => {
    // mode_state 첫 수신 전까진 online 상태 미정 — welcome 이 처리
  });
}

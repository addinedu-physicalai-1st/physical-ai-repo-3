/* ws.js — WebSocket 클라이언트 (spec §11.2)
 *
 * 자동 재연결 (지수 백오프 1s → 30s).
 * type 별 콜백 등록 (`wsClient.on(type, cb)`).
 * 동일 page 내 store.js 와 협력.
 */

class WSClient {
  constructor(url) {
    this.url = url;
    this.handlers = new Map();       // type → [callback, ...]
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.ws = null;
    this.opened = false;
    this.connect();
  }

  connect() {
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      console.error('[ws] construct failed:', e);
      this.reconnect();
      return;
    }
    this.ws.onopen = () => {
      console.info('[ws] open', this.url);
      this.reconnectDelay = 1000;
      this.opened = true;
      this._emit('ws:open', {});
    };
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        this._dispatch(msg);
      } catch (err) {
        console.warn('[ws] bad message', err, e.data);
      }
    };
    this.ws.onclose = (e) => {
      if (this.opened) {
        console.info('[ws] close', e.code);
        this.opened = false;
        this._emit('ws:close', { code: e.code });
      }
      this.reconnect();
    };
    this.ws.onerror = (e) => {
      console.warn('[ws] error', e);
    };
  }

  reconnect() {
    setTimeout(() => this.connect(), this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  _dispatch(msg) {
    const handlers = this.handlers.get(msg.type) || [];
    handlers.forEach(h => {
      try { h(msg); } catch (e) { console.error('[ws] handler error', e); }
    });
    // wildcard
    const star = this.handlers.get('*') || [];
    star.forEach(h => h(msg));
  }

  _emit(type, data) {
    const handlers = this.handlers.get(type) || [];
    handlers.forEach(h => h({ type, data }));
  }

  on(type, callback) {
    if (!this.handlers.has(type)) this.handlers.set(type, []);
    this.handlers.get(type).push(callback);
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
      return true;
    }
    console.warn('[ws] not open, dropped:', obj);
    return false;
  }
}

// 전역 인스턴스 — page 가 로드되면 자동 연결
const wsUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/dashboard`;
window.wsClient = new WSClient(wsUrl);

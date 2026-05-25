/* api.js — REST fetch wrapper.
 *
 * 본 단계 (M1) 에는 GET /status, /health 정도만 사용. 모드 전환은 WS send 우선.
 */

async function apiGet(path) {
  const res = await fetch(`/api/v1${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(`POST ${path} failed: ${res.status}`);
    err.payload = json;
    err.status = res.status;
    throw err;
  }
  return json;
}

window.api = { get: apiGet, post: apiPost };

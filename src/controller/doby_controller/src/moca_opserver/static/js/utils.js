/* utils.js — 작은 헬퍼 모음 */

function formatTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  } catch { return ''; }
}

function formatRelative(iso) {
  if (!iso) return '';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (isNaN(ms)) return '';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  } catch { return ''; }
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

window.utils = { formatTime, formatRelative, clamp };

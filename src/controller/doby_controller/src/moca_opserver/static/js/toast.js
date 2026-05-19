/* toast.js — 전역 toast 헬퍼.
 *
 * 사용:  toast('메시지', 'info'|'warn'|'error')
 * 의존:  components.css 의 .toast / .toast--show / .toast--info|warn|error
 *
 * mode-buttons.js 의 _toast() 와 동일 동작이나 페이지 전역 호출 가능.
 */

(function () {
  function toast(message, level) {
    const el = document.createElement('div');
    el.className = `toast toast--${level || 'info'}`;
    el.textContent = message;
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('toast--show'));
    setTimeout(() => {
      el.classList.remove('toast--show');
      setTimeout(() => el.remove(), 300);
    }, 3000);
  }
  window.toast = toast;
})();

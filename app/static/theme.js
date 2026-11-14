/* Theme preference is browser-local; System tracks OS changes. */
(function () {
  'use strict';
  const KEY = 'syllabus-auditor-appearance';
  const valid = new Set(['light', 'dark', 'system']);
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let sessionPreference = null;
  function getPreference() {
    try {
      const value = window.localStorage.getItem(KEY);
      return valid.has(value) ? value : 'system';
    } catch (_) { return sessionPreference || 'system'; }
  }
  function apply() {
    const preference = getPreference();
    const mode = preference === 'system' ? (media && media.matches ? 'dark' : 'light') : preference;
    document.documentElement.setAttribute('data-theme', mode);
    document.documentElement.style.colorScheme = mode;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = mode === 'dark' ? '#121a29' : '#ffffff';
    return mode;
  }
  function setPreference(value) {
    if (!valid.has(value)) throw Error('Unsupported appearance preference');
    try { window.localStorage.setItem(KEY, value); } catch (_) { /* Private browser: session-only fallback. */
      // Reflect the preference for this session even when storage is unavailable.
      sessionPreference = value;
      apply();
      return;
    }
    apply();
  }
  window.SyllabusTheme = {getPreference, setPreference, apply};
  if (media) {
    if (typeof media.addEventListener === 'function') media.addEventListener('change', () => { if(getPreference() === 'system') apply(); });
    else if (typeof media.addListener === 'function') media.addListener(() => { if(getPreference() === 'system') apply(); });
  }
  apply();
})();

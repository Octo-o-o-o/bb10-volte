(() => {
  const root = document.documentElement;
  root.dataset.enhanced = 'true';
  let language = 'zh-CN';
  try {
    const preferred = navigator.languages?.[0] || navigator.language;
    if (typeof preferred === 'string' && preferred.trim()) {
      const tag = preferred.trim();
      if (/^(zh|zho|chi|cmn|yue)([-_]|$)/i.test(tag)) language = 'zh-CN';
      else if (!/^(c|posix|und|unknown)$/i.test(tag) && /^[a-z]{2,3}([-_][a-z0-9]{1,8})*$/i.test(tag)) language = 'en';
    }
  } catch { /* The system language is unavailable; keep Chinese. */ }
  root.dataset.systemLanguage = language;
  // Neutral URLs follow the browser. Explicit language URLs stay shareable.
  const neutralTarget = { '/': '/en/index.html', '/guide': '/en/guide.html' }[location.pathname];
  if (neutralTarget && language === 'en') {
    location.replace(`${neutralTarget}${location.search}${location.hash}`);
  }
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try {
    const saved = localStorage.getItem('bb10-volte-theme');
    if (['system', 'light', 'dark'].includes(saved)) preference = saved;
  } catch {}
  const resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
  root.dataset.appearance = preference;
  root.dataset.theme = resolved;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.content = resolved === 'dark' ? '#171d19' : '#f4f5f0';
})();

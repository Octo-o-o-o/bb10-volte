export const REPOSITORY_URL = 'https://github.com/Octo-o-o-o/bb10-volte';
export const RELEASE_KEYS = ['windows', 'windows-sha', 'mac', 'mac-sha', 'source', 'source-sha'];
// Update these together with the static HTML only after both copies are verified.
export const RELEASE_TAG = 'v0.5.0-r8';
export const MIRROR_BASE = 'https://bb10-downloads.octoooo.com';

export function selectRelease(releases) {
  if (!Array.isArray(releases)) return null;
  const candidates = releases
    .filter((release) => release && release.draft === false && /^v\d+\.\d+\.\d+-r\d+$/.test(release.tag_name))
    .sort((a, b) => Date.parse(b.published_at || b.created_at || 0) - Date.parse(a.published_at || a.created_at || 0));

  for (const release of candidates) {
    if (!Array.isArray(release.assets)) continue;
    const tag = release.tag_name;
    const version = tag.slice(1);
    const basename = `bb10-volte-${version}`;
    const names = {
      windows: `${basename}-windows-x64.exe`,
      'windows-sha': `${basename}-windows-x64.exe.sha256`,
      mac: `${basename}-macos-universal.dmg`,
      'mac-sha': `${basename}-macos-universal.dmg.sha256`,
      source: `${basename}-experimental.zip`,
      'source-sha': `${basename}-experimental.zip.sha256`,
      checksums: 'SHA256SUMS.txt',
    };
    const available = new Set(release.assets.map((asset) => asset?.name));
    if (!Object.values(names).every((name) => available.has(name))) continue;
    const base = `${REPOSITORY_URL}/releases/download/${tag}`;
    const urls = Object.fromEntries(Object.entries(names).map(([key, name]) => [key, `${base}/${name}`]));
    return { tag, version, page: `${REPOSITORY_URL}/releases/tag/${tag}`, urls };
  }
  return null;
}

export function applyRelease(documentRoot, release) {
  if (!release) return;
  for (const key of RELEASE_KEYS) {
    documentRoot.querySelectorAll(`[data-download="${key}"]`).forEach((link) => {
      link.href = release.tag === RELEASE_TAG
        ? release.urls[key].replace(`${REPOSITORY_URL}/releases/download`, MIRROR_BASE)
        : release.urls[key];
    });
    documentRoot.querySelectorAll(`[data-github-download="${key}"]`).forEach((link) => {
      link.href = release.urls[key];
    });
  }
  documentRoot.querySelectorAll('[data-release-version]').forEach((element) => {
    element.textContent = release.tag;
  });
  documentRoot.querySelectorAll('[data-release-link]').forEach((link) => {
    link.href = release.page;
  });
  documentRoot.querySelectorAll('[data-release-checksums]').forEach((link) => {
    link.href = release.tag === RELEASE_TAG
      ? release.urls.checksums.replace(`${REPOSITORY_URL}/releases/download`, MIRROR_BASE)
      : release.urls.checksums;
  });
  const filenames = {
    windows: `bb10-volte-${release.version}-windows-x64.exe`,
    mac: `bb10-volte-${release.version}-macos-universal.dmg`,
  };
  documentRoot.querySelectorAll('[data-package-file]').forEach((element) => {
    element.textContent = filenames[element.dataset.packageFile];
  });
  const commands = {
    windows: `Get-FileHash "$HOME\\Downloads\\${filenames.windows}" -Algorithm SHA256`,
    mac: `shasum -a 256 "$HOME/Downloads/${filenames.mac}"`,
  };
  documentRoot.querySelectorAll('[data-checksum-command]').forEach((element) => {
    element.textContent = commands[element.dataset.checksumCommand];
  });
}

function initializeAppearance() {
  const select = document.querySelector('#appearance');
  if (!select) return;
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const root = document.documentElement;
  const apply = (preference, save = false) => {
    const resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    root.dataset.appearance = preference;
    root.dataset.theme = resolved;
    select.value = preference;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = resolved === 'dark' ? '#171d19' : '#f4f5f0';
    if (save) {
      try { localStorage.setItem('bb10-volte-theme', preference); } catch {}
    }
  };
  apply(['system', 'light', 'dark'].includes(root.dataset.appearance) ? root.dataset.appearance : 'system');
  select.addEventListener('change', () => apply(select.value, true));
  media.addEventListener('change', () => {
    if (root.dataset.appearance === 'system') apply('system');
  });
}

export function menuLabel(language, open) {
  return language === 'en'
    ? (open ? 'Close navigation menu' : 'Open navigation menu')
    : (open ? '关闭导航菜单' : '打开导航菜单');
}

function initializeLanguage() {
  const language = document.documentElement.lang;
  document.querySelectorAll('[data-language-switch]').forEach((link) => {
    // The same section IDs exist in each language, including guide deep links.
    const updateDestination = () => {
      const destination = new URL(link.href);
      destination.search = location.search;
      destination.hash = location.hash;
      link.href = destination.href;
    };
    updateDestination();
    window.addEventListener('hashchange', updateDestination);
    link.addEventListener('click', updateDestination);
  });
  document.querySelectorAll('[data-star-count]').forEach((element) => {
    element.textContent = language === 'en' ? 'Star on GitHub' : '在 GitHub 点个 Star';
  });
}

function initializeNotFoundLanguage() {
  const root = document.documentElement;
  if (root.lang !== 'zh-CN' || root.dataset.systemLanguage !== 'en' ||
      location.pathname === '/404.html' || !document.querySelector('.error-hero')) return;
  // Localize the existing 404 in place so the original HTTP 404 and URL remain intact.
  root.lang = 'en';
  document.title = 'Page not found | BB10 VoLTE';
  document.querySelector('meta[name="description"]').content = 'This page could not be found. Visit the BB10 VoLTE homepage or open the setup guide.';
  document.querySelector('.skip-link').textContent = 'Skip to content';
  document.querySelectorAll('.brand[href="/index.html"]').forEach((link) => { link.href = '/en/index.html'; });
  const languageSwitch = document.querySelector('[data-language-switch]');
  languageSwitch.dataset.languageSwitch = 'zh-CN';
  languageSwitch.href = '/404.html';
  languageSwitch.lang = languageSwitch.hreflang = 'zh-CN';
  languageSwitch.setAttribute('aria-label', '切换为中文');
  languageSwitch.textContent = '中文';
  const appearance = document.querySelector('#appearance');
  appearance.setAttribute('aria-label', 'Appearance');
  for (const [value, label] of Object.entries({ system: 'System', light: 'Light', dark: 'Dark' })) {
    appearance.querySelector(`option[value="${value}"]`).textContent = label;
  }
  const heading = document.querySelector('.error-hero h1');
  heading.replaceChildren('This page', document.createElement('br'));
  const emphasis = document.createElement('em');
  emphasis.textContent = 'could not be found.';
  heading.append(emphasis);
  document.querySelector('.error-hero .hero-lead').textContent = 'The link may have changed, or the address may contain a typo. Go back to the homepage or open the setup guide.';
  const home = document.querySelector('.error-hero .button-primary');
  home.href = '/en/index.html';
  home.textContent = 'Back to home';
  const guide = document.querySelector('.error-hero .button-secondary');
  guide.href = '/en/guide.html';
  guide.textContent = 'Read the guide';
  document.querySelector('.footer-brand p').textContent = 'Keep your BlackBerry going.';
}

function initializeMenu() {
  const toggle = document.querySelector('#menu-toggle');
  const navigation = document.querySelector('#site-nav');
  if (!toggle || !navigation) return;
  const close = (focus = false) => {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', menuLabel(document.documentElement.lang, false));
    navigation.dataset.open = 'false';
    if (focus) toggle.focus();
  };
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', menuLabel(document.documentElement.lang, open));
    navigation.dataset.open = String(open);
  });
  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') close(true);
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.site-header')) close();
  });
  window.matchMedia('(min-width: 1101px)').addEventListener('change', (event) => {
    if (event.matches) close();
  });
}

async function fetchJson(url, timeout = 6000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/vnd.github+json' },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function initializeGithubData() {
  if (document.querySelector('[data-download]')) {
    fetchJson('https://api.github.com/repos/Octo-o-o-o/bb10-volte/releases?per_page=10')
      .then((releases) => applyRelease(document, selectRelease(
        Array.isArray(releases) ? releases.filter((release) => release.tag_name === RELEASE_TAG) : []
      )))
      .catch(() => {});
  }
  if (!document.querySelector('[data-star-count]')) return;
  fetchJson(REPOSITORY_URL.replace('https://github.com/', 'https://api.github.com/repos/'))
    .then((repository) => {
      if (!Number.isSafeInteger(repository?.stargazers_count) || repository.stargazers_count < 0) return;
      document.querySelectorAll('[data-star-count]').forEach((element) => {
        const language = document.documentElement.lang;
        const label = language === 'en' ? 'Star on GitHub' : '在 GitHub 点个 Star';
        element.textContent = `${label} · ${repository.stargazers_count.toLocaleString(language)}`;
      });
    })
    .catch(() => {});
}

if (typeof document !== 'undefined') {
  initializeNotFoundLanguage();
  initializeLanguage();
  initializeAppearance();
  initializeMenu();
  initializeGithubData();
  document.querySelectorAll('[data-current-year]').forEach((element) => {
    element.textContent = String(new Date().getFullYear());
  });
}

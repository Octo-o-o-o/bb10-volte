import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { applyRelease, menuLabel, RELEASE_KEYS, RELEASE_TAG, MIRROR_BASE, REPOSITORY_URL, selectRelease } from '../src/site.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const pages = ['index.html', 'guide.html', '404.html', 'en/index.html', 'en/guide.html', 'en/404.html'];
const html = Object.fromEntries(await Promise.all(pages.map(async (page) => [page, await readFile(path.join(root, 'dist', page), 'utf8')])));
const fallbackBase = 'https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8';

function idsFor(source) {
  return new Set([...source.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]));
}

function releaseFixture(tag = 'v0.3.4-r1', overrides = {}) {
  const version = tag.slice(1);
  const basename = `bb10-volte-${version}`;
  const names = [
    `${basename}-windows-x64.exe`, `${basename}-windows-x64.exe.sha256`,
    `${basename}-macos-universal.dmg`, `${basename}-macos-universal.dmg.sha256`,
    `${basename}-experimental.zip`, `${basename}-experimental.zip.sha256`, 'SHA256SUMS.txt',
  ];
  return {
    tag_name: tag,
    draft: false,
    prerelease: true,
    published_at: '2026-11-01T00:00:00Z',
    assets: names.map((name) => ({ name, browser_download_url: `https://example.invalid/${name}` })),
    ...overrides,
  };
}

test('every page has unique ids and working local fragment links', () => {
  for (const [page, source] of Object.entries(html)) {
    const ids = [...source.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
    assert.equal(new Set(ids).size, ids.length, `${page}: duplicate ids`);
    for (const match of source.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const reference = match[1];
      if (!reference.includes('#')) continue;
      const [targetPage, fragment] = reference.split('#');
      if (!fragment || reference.startsWith('http')) continue;
      const destination = targetPage
        ? path.posix.normalize(targetPage.startsWith('/') ? targetPage.slice(1) : path.posix.join(path.posix.dirname(page), targetPage))
        : page;
      assert.ok(pages.includes(destination), `${page}: unknown local page ${destination}`);
      assert.ok(idsFor(html[destination]).has(fragment), `${page}: missing ${destination}#${fragment}`);
    }
  }
});

test('all external links are HTTPS and new tabs are isolated', () => {
  for (const [page, source] of Object.entries(html)) {
    for (const match of source.matchAll(/<a\b[^>]*>/g)) {
      const anchor = match[0];
      const href = anchor.match(/href="([^"]+)"/)?.[1];
      if (href?.startsWith('http')) assert.ok(href.startsWith('https://'), `${page}: insecure ${href}`);
      if (anchor.includes('target="_blank"')) {
        const rel = anchor.match(/rel="([^"]+)"/)?.[1] || '';
        assert.ok(rel.includes('noopener') && rel.includes('noreferrer'), `${page}: unsafe ${anchor}`);
      }
    }
  }
});

test('verified Windows and macOS downloads are available without JavaScript', () => {
  for (const page of ['index.html', 'guide.html', 'en/index.html', 'en/guide.html']) {
    assert.match(html[page], new RegExp(`data-download="windows" href="${fallbackBase.replaceAll('.', '\\.')}-windows-x64\\.exe"`));
    assert.match(html[page], new RegExp(`data-download="mac" href="${fallbackBase.replaceAll('.', '\\.')}-macos-universal\\.dmg"`));
  }
  assert.ok(html['index.html'].includes(`${fallbackBase}-windows-x64.exe.sha256`));
  assert.ok(html['index.html'].includes(`${fallbackBase}-macos-universal.dmg.sha256`));
  assert.ok(html['index.html'].includes(`${fallbackBase}-experimental.zip`));
  assert.ok(html['index.html'].includes('/SHA256SUMS.txt'));
});

test('required project, guide, star and OctoLab links are present', () => {
  assert.ok(html['index.html'].includes('https://github.com/Octo-o-o-o/bb10-volte'));
  assert.ok(html['index.html'].includes('data-star-count'));
  assert.ok(html['index.html'].includes('href="guide.html"'));
  for (const page of ['index.html', 'guide.html', 'en/index.html', 'en/guide.html']) {
    assert.ok(html[page].includes('href="https://octoooo.com"'));
    assert.ok(html[page].includes('data-current-year'));
  }
});

test('release selection accepts the newest complete public prerelease', () => {
  const older = releaseFixture('v0.3.3-r3', { published_at: '2026-10-01T00:00:00Z' });
  const newer = releaseFixture('v0.3.4-r1');
  const selected = selectRelease([older, newer]);
  assert.equal(selected.tag, 'v0.3.4-r1');
  assert.equal(selected.version, '0.3.4-r1');
  assert.equal(selected.page, `${REPOSITORY_URL}/releases/tag/v0.3.4-r1`);
  assert.equal(selected.urls.windows, `${REPOSITORY_URL}/releases/download/v0.3.4-r1/bb10-volte-0.3.4-r1-windows-x64.exe`);
  assert.ok(!Object.values(selected.urls).some((url) => url.includes('example.invalid')));
});

test('release selection rejects drafts, malformed tags and incomplete assets', () => {
  assert.equal(selectRelease(null), null);
  assert.equal(selectRelease([]), null);
  assert.equal(selectRelease([releaseFixture('v0.3.4-r1', { draft: true })]), null);
  assert.equal(selectRelease([releaseFixture('latest')]), null);
  const incomplete = releaseFixture();
  incomplete.assets = incomplete.assets.filter((asset) => !asset.name.endsWith('.dmg'));
  assert.equal(selectRelease([incomplete]), null);
  const noChecksums = releaseFixture();
  noChecksums.assets = noChecksums.assets.filter((asset) => asset.name !== 'SHA256SUMS.txt');
  assert.equal(selectRelease([noChecksums]), null);
});

test('release selection skips a broken newer release and keeps an older complete one', () => {
  const older = releaseFixture('v0.3.3-r3', { published_at: '2026-10-01T00:00:00Z' });
  const newer = releaseFixture('v0.3.4-r1');
  newer.assets.pop();
  assert.equal(selectRelease([newer, older]).tag, older.tag_name);
});

test('applying a release updates every download and release link', () => {
  const groups = new Map();
  const get = (selector) => {
    if (!groups.has(selector)) groups.set(selector, [{ href: '', textContent: '', dataset: {} }, { href: '', textContent: '', dataset: {} }]);
    return groups.get(selector);
  };
  const documentRoot = { querySelectorAll: get };
  const packageFile = { textContent: '', dataset: { packageFile: 'windows' } };
  const checksumCommand = { textContent: '', dataset: { checksumCommand: 'mac' } };
  groups.set('[data-package-file]', [packageFile]);
  groups.set('[data-checksum-command]', [checksumCommand]);
  const release = selectRelease([releaseFixture()]);
  applyRelease(documentRoot, release);
  assert.equal(packageFile.textContent, 'bb10-volte-0.3.4-r1-windows-x64.exe');
  assert.equal(checksumCommand.textContent, 'shasum -a 256 "$HOME/Downloads/bb10-volte-0.3.4-r1-macos-universal.dmg"');
  for (const key of RELEASE_KEYS) {
    for (const element of get(`[data-download="${key}"]`)) assert.equal(element.href, release.urls[key]);
  }
  for (const element of get('[data-release-version]')) assert.equal(element.textContent, release.tag);
  for (const element of get('[data-release-link]')) assert.equal(element.href, release.page);
  for (const element of get('[data-release-checksums]')) assert.equal(element.href, release.urls.checksums);
});

test('language pages have reciprocal switches, localized metadata and matching sections', () => {
  for (const name of ['index.html', 'guide.html']) {
    const chinese = html[name];
    const english = html[`en/${name}`];
    assert.match(chinese, /<html lang="zh-CN">/);
    assert.match(english, /<html lang="en">/);
    assert.ok(chinese.includes(`data-language-switch="en" href="en/${name}"`));
    assert.ok(english.includes(`data-language-switch="zh-CN" href="../${name}"`));
    assert.match(english, /property="og:locale" content="en_US"/);
    assert.match(chinese, /property="og:locale" content="zh_CN"/);
    for (const language of ['zh-CN', 'en', 'x-default']) {
      assert.ok(chinese.includes(`hreflang="${language}"`));
      assert.ok(english.includes(`hreflang="${language}"`));
    }
    assert.deepEqual(idsFor(english), idsFor(chinese));
    const englishCopy = english.replace(/<a class="language-switch"[^>]*>.*?<\/a>/g, '').replace(/\(连接手机\)|\(连接帮助\)/g, '');
    assert.ok(!/\p{Script=Han}/u.test(englishCopy), `${name}: untranslated Chinese content`);
  }
});

test('English homepage and social preview use the English interface screenshot', () => {
  assert.match(html['index.html'], /<img src="assets\/app-status\.png"/);
  assert.match(html['en/index.html'], /<img src="\.\.\/assets\/app-status-en\.jpg"/);
  assert.match(html['en/index.html'], /property="og:image" content="https:\/\/bb10-volte\.octoooo\.com\/assets\/app-status-en\.jpg"/);
  assert.match(html['en/index.html'], /Earlier interface · recorded status/);
});

test('both languages retain safety requirements and experimental limits', () => {
  for (const name of ['index.html', 'guide.html']) {
    for (const language of ['', 'en/']) {
      const source = html[`${language}${name}`];
      for (const required of ['SQN100-3', '10.3.3.3216', '460-01', 'Q20', 'Q30', 'SHA-256']) assert.ok(source.includes(required));
      assert.match(source, language ? /(?:erase|wipes)/ : /清空/);
      assert.match(source, language ? /(?:experimental|Experimental)/ : /实验/);
    }
  }
});

test('dynamic menu labels use the page language', () => {
  assert.equal(menuLabel('en', true), 'Close navigation menu');
  assert.equal(menuLabel('en', false), 'Open navigation menu');
  assert.equal(menuLabel('zh-CN', true), '关闭导航菜单');
  assert.equal(menuLabel('zh-CN', false), '打开导航菜单');
});

test('curated release retains the R2 route and a version-matched GitHub alternative', () => {
  const groups = new Map();
  const get = (selector) => {
    if (!groups.has(selector)) groups.set(selector, []);
    return groups.get(selector);
  };
  for (const key of RELEASE_KEYS) {
    groups.set(`[data-download="${key}"]`, [{ href: '' }]);
    groups.set(`[data-github-download="${key}"]`, [{ href: '' }]);
  }
  groups.set('[data-release-checksums]', [{ href: '' }]);
  const release = selectRelease([releaseFixture(RELEASE_TAG)]);
  applyRelease({ querySelectorAll: get }, release);
  for (const key of RELEASE_KEYS) {
    assert.equal(get(`[data-download="${key}"]`)[0].href, release.urls[key].replace(`${REPOSITORY_URL}/releases/download`, MIRROR_BASE));
    assert.equal(get(`[data-github-download="${key}"]`)[0].href, release.urls[key]);
  }
  assert.equal(get('[data-release-checksums]')[0].href, `${MIRROR_BASE}/${RELEASE_TAG}/SHA256SUMS.txt`);
});

test('both translations retain the extra restart and offline SIM-change scope', () => {
  for (const page of ['index.html', 'guide.html', 'en/index.html', 'en/guide.html']) {
    const source = html[page];
    for (const variant of ['SQN100-3', 'SQC100-2', 'SQW100-4']) assert.ok(source.includes(variant));
    assert.ok(source.includes('acceptance.json'));
    assert.ok(source.includes('data-github-download="windows"'));
    assert.ok(source.includes('bb10-downloads.octoooo.com/v0.5.0-r8/'));
    assert.match(source, page.startsWith('en/') ? /extra normal restart|additional normal restart/ : /再正常重启一次|还需一次正常重启/);
  }
});

test('security headers allow only local assets and the GitHub API', async () => {
  const headers = await readFile(path.join(root, 'dist', '_headers'), 'utf8');
  assert.ok(headers.includes("default-src 'self'"));
  assert.ok(headers.includes("script-src 'self'"));
  assert.ok(headers.includes("connect-src 'self' https://api.github.com"));
  assert.ok(headers.includes("frame-ancestors 'none'"));
  assert.ok(headers.includes('X-Content-Type-Options: nosniff'));
  assert.ok(!headers.includes("script-src 'self' 'unsafe-inline'"));
});

test('published source does not expose workstation paths or the reference brand', async () => {
  for (const file of [...pages, 'styles.css', 'guide.css', 'site.js', 'appearance.js']) {
    const source = await readFile(path.join(root, 'dist', file), 'utf8');
    assert.ok(!/C:[\\/]|\/Users\/|Anyvia|手边/.test(source), `${file}: local path or unrelated brand`);
  }
});

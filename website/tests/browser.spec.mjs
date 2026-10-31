import { test, expect } from '@playwright/test';

const windowsFallback = 'https://bb10-downloads.octoooo.com/v0.5.0-r8/bb10-volte-0.5.0-r8-windows-x64.exe';

test('homepage renders real content, image and downloads without script errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page).toHaveTitle(/BB10 VoLTE/);
  await expect(page.locator('h1')).toContainText('用上 VoLTE');
  await expect(page.locator('#how')).toBeVisible();
  await expect(page.locator('#compatibility')).toBeVisible();
  await expect(page.locator('#download')).toBeVisible();
  await expect(page.locator('.software-figure > img')).toHaveJSProperty('naturalWidth', 1000);
  await expect(page.locator('[data-download="windows"]').first()).toHaveAttribute('href', /bb10-volte-.*-windows-x64\.exe$/);
  await expect(page.locator('[data-download="mac"]').first()).toHaveAttribute('href', /bb10-volte-.*-macos-universal\.dmg$/);
  await expect(page.locator('.footer-links a[href="https://octoooo.com"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test('all pages fit narrow, tablet and desktop viewports', async ({ page }) => {
  for (const pathname of ['/', '/guide.html', '/missing-page', '/en/', '/en/guide.html', '/en/nested/missing-page']) {
    for (const width of [320, 390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(pathname);
      const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
      expect(dimensions.content, `${pathname} overflows at ${width}px`).toBeLessThanOrEqual(dimensions.viewport + 1);
    }
  }
});

test('appearance selection persists across reloads', async ({ page }) => {
  await page.goto('/');
  await page.locator('#appearance').selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#171d19');
  await page.reload();
  await expect(page.locator('#appearance')).toHaveValue('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.locator('#appearance').selectOption('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.locator('#appearance').selectOption('system');
  await expect(page.locator('html')).toHaveAttribute('data-appearance', 'system');
});

test('mobile menu opens, closes with Escape and navigates to the guide', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const toggle = page.locator('#menu-toggle');
  await expect(page.locator('#site-nav')).toBeHidden();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#site-nav')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
  await toggle.click();
  await page.locator('#site-nav a[href="guide.html"]').click();
  await expect(page).toHaveURL(/\/guide\.html$/);
  await expect(page.locator('h1')).toContainText('真实通话验收');
});

test('FAQ opens and closes with native keyboard-accessible controls', async ({ page }) => {
  await page.goto('/#faq');
  const first = page.locator('.faq-list details').first();
  await first.locator('summary').click();
  await expect(first).toHaveAttribute('open', '');
  await expect(first.locator('p')).toBeVisible();
  await first.locator('summary').press('Enter');
  await expect(first).not.toHaveAttribute('open', '');
});

test('GitHub API failure preserves verified release downloads and star label', async ({ page }) => {
  await page.route('https://api.github.com/**', (route) => route.abort());
  await page.goto('/');
  await expect(page.locator('[data-download="windows"]').first()).toHaveAttribute('href', windowsFallback);
  await expect(page.locator('[data-release-version]').first()).toHaveText('v0.5.0-r8');
  await expect(page.locator('[data-star-count]')).toHaveText('在 GitHub 点个 Star');
});

test('guide updates version, package names and checksum commands together', async ({ page }) => {
  const tag = 'v0.5.0-r8';
  const basename = 'bb10-volte-0.5.0-r8';
  const names = [
    `${basename}-windows-x64.exe`, `${basename}-windows-x64.exe.sha256`,
    `${basename}-macos-universal.dmg`, `${basename}-macos-universal.dmg.sha256`,
    `${basename}-experimental.zip`, `${basename}-experimental.zip.sha256`, 'SHA256SUMS.txt',
  ];
  await page.route('https://api.github.com/repos/Octo-o-o-o/bb10-volte/releases?per_page=10', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{ tag_name: tag, draft: false, published_at: '2026-11-01T00:00:00Z', assets: names.map((name) => ({ name })) }]),
  }));
  await page.goto('/guide.html');
  await expect(page.locator('[data-release-version]').first()).toHaveText(tag);
  await expect(page.locator('[data-package-file="windows"]')).toHaveText(`${basename}-windows-x64.exe`);
  await expect(page.locator('[data-package-file="mac"]')).toHaveText(`${basename}-macos-universal.dmg`);
  await expect(page.locator('[data-checksum-command="windows"]')).toContainText(`${basename}-windows-x64.exe`);
  await expect(page.locator('[data-checksum-command="mac"]')).toContainText(`${basename}-macos-universal.dmg`);
  await expect(page.locator('[data-release-link]')).toHaveAttribute('href', new RegExp(`${tag}$`));
});

test('an older API release cannot downgrade curated downloads or mix mirror versions', async ({ page }) => {
  const tag = 'v0.3.3-r5';
  const basename = 'bb10-volte-0.3.3-r5';
  const names = ['windows-x64.exe', 'windows-x64.exe.sha256', 'macos-universal.dmg', 'macos-universal.dmg.sha256', 'experimental.zip', 'experimental.zip.sha256'].map((suffix) => `${basename}-${suffix}`);
  names.push('SHA256SUMS.txt');
  await page.route('https://api.github.com/**/releases?per_page=10', (route) => route.fulfill({
    contentType: 'application/json', body: JSON.stringify([{ tag_name: tag, draft: false, published_at: '2026-11-02T00:00:00Z', assets: names.map((name) => ({ name })) }]),
  }));
  await page.goto('/guide.html');
  await expect(page.locator('[data-release-version]').first()).toHaveText('v0.5.0-r8');
  await expect(page.locator('[data-download="windows"]').first()).toHaveAttribute('href', windowsFallback);
  await expect(page.locator('[data-github-download="windows"]').first()).toHaveAttribute('href', /github\.com\/.*\/v0\.5\.0-r8\/bb10-volte-0\.5\.0-r8-windows-x64\.exe$/);
});

test('guide uses a readable single-column article on desktop', async ({ page }) => {
  await page.goto('/guide.html');
  await expect(page.locator('.guide-toc')).toBeVisible();
  const content = await page.locator('.guide-content').boundingBox();
  const heading = await page.locator('#prepare-title').boundingBox();
  expect(content.width).toBeGreaterThan(600);
  expect(heading.height).toBeLessThan(150);
  await page.locator('.guide-toc a[href="#verify"]').click();
  await expect(page).toHaveURL(/guide\.html#verify$/);
  await expect(page.locator('#verify')).toBeInViewport();
});

test('core content and downloads work with JavaScript disabled', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, locale: 'zh-CN', baseURL });
  const page = await context.newPage();
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
  await expect(page.locator('[data-download="windows"]').first()).toHaveAttribute('href', windowsFallback);
  await page.goto('/guide.html');
  await expect(page.locator('#prepare')).toBeVisible();
  await expect(page.locator('[data-download="mac"]').first()).toHaveAttribute('href', /macos-universal\.dmg$/);
  await page.getByRole('link', { name: 'Switch to English' }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('#prepare')).toContainText('Preparation and risks');
  await expect(page.locator('[data-download="mac"]').first()).toHaveAttribute('href', /macos-universal\.dmg$/);
  await page.goto('/en/index.html');
  await expect(page.locator('h1')).toContainText('Bring VoLTE');
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(page.locator('#site-nav')).toBeVisible();
  await expect(page.locator('#site-nav a[href="guide.html"]')).toBeVisible();
  await context.close();
});

test('language switch preserves guide section and query while the homepage follows the browser', async ({ page }) => {
  await page.goto('/guide.html?from=test#verify');
  await page.locator('[data-language-switch]').click();
  await expect(page).toHaveURL(/\/en\/guide\.html\?from=test#verify$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('#verify')).toBeInViewport();
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await page.locator('[data-language-switch]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
});

test('language switch follows sections selected after page load', async ({ page }) => {
  await page.goto('/guide.html');
  await page.locator('.guide-toc a[href="#acceptance"]').click();
  await page.locator('[data-language-switch]').click();
  await expect(page).toHaveURL(/\/en\/guide\.html#acceptance$/);
  await expect(page.locator('#acceptance')).toBeInViewport();
});

test('English browser gets English homepage while explicit Chinese URLs remain Chinese', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ locale: 'en-US', baseURL });
  const page = await context.newPage();
  await page.goto('/?from=browser#download');
  await expect(page).toHaveURL(/\/en\/index\.html\?from=browser#download$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('.software-figure > img')).toHaveJSProperty('naturalWidth', 1502);
  await expect(page.locator('.software-figure > img')).toHaveAttribute('src', '../assets/app-status-en.jpg');
  await page.goto('/index.html');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await page.goto('/guide?from=browser#verify');
  await expect(page).toHaveURL(/\/en\/guide\.html\?from=browser#verify$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await context.close();
});

test('a neutral missing route keeps its 404 status while using the browser language', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ locale: 'ja-JP', baseURL });
  const page = await context.newPage();
  const response = await page.goto('/missing-english?from=test#details');
  expect(response.status()).toBe(404);
  await expect(page).toHaveURL(/\/missing-english\?from=test#details$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('h1')).toContainText('could not be found');
  await expect(page.getByRole('link', { name: 'Read the guide' })).toHaveAttribute('href', '/en/guide.html');
  await context.close();
});

test('homepage uses the first preferred language and falls back to Chinese when unavailable', async ({ browser, baseURL }) => {
  for (const [languages, language, expected] of [
    [['zh-Hant-TW', 'en-US'], 'zh-Hant-TW', 'zh-CN'],
    [['ja-JP', 'zh-CN'], 'ja-JP', 'en'],
    [['und'], 'und', 'zh-CN'],
    [[], undefined, 'zh-CN'],
  ]) {
    const context = await browser.newContext({ baseURL });
    await context.addInitScript(({ languages, language }) => {
      Object.defineProperty(navigator, 'languages', { get: () => languages });
      Object.defineProperty(navigator, 'language', { get: () => language });
    }, { languages, language });
    const page = await context.newPage();
    await page.goto('/?source=language#download');
    await expect(page.locator('html')).toHaveAttribute('lang', expected);
    expect(new URL(page.url()).search + new URL(page.url()).hash).toBe('?source=language#download');
    await context.close();
  }
});

test('English mobile menu labels and theme stay localized when used', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/en/index.html');
  const toggle = page.locator('#menu-toggle');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-label', 'Close navigation menu');
  await page.keyboard.press('Escape');
  await expect(toggle).toHaveAttribute('aria-label', 'Open navigation menu');
  await page.locator('#appearance').selectOption('dark');
  await page.locator('[data-language-switch]').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('English downloads and labels survive GitHub failure', async ({ page }) => {
  await page.route('https://api.github.com/**', (route) => route.abort());
  await page.goto('/en/');
  await expect(page.locator('[data-download="windows"]').first()).toHaveAttribute('href', windowsFallback);
  await expect(page.locator('[data-star-count]')).toHaveText('Star on GitHub');
  await expect(page.locator('meta[property="og:locale"]')).toHaveAttribute('content', 'en_US');
});

test('nested English missing route has working assets and recovery links', async ({ page }) => {
  const response = await page.goto('/en/nested/not-found');
  expect(response.status()).toBe(404);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(await page.locator('.brand-mark').first().evaluate((image) => image.complete && image.naturalWidth > 0)).toBe(true);
  await page.getByRole('link', { name: 'Back to home' }).click();
  await expect(page.locator('#hero-title')).toContainText('Bring VoLTE');
});

test('blocked local storage does not break English content or switching', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Storage blocked', 'SecurityError'); } });
  });
  await page.goto('/en/index.html');
  await expect(page.locator('h1')).toContainText('Bring VoLTE');
  await page.locator('[data-language-switch]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
});

test('capture bilingual desktop and mobile layouts for visual review', async ({ page }) => {
  await page.route('https://api.github.com/**', (route) => route.abort());
  for (const language of ['zh', 'en']) {
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(language === 'en' ? '/en/index.html' : '/index.html');
      await page.screenshot({ path: `.playwright/bilingual-${language}-${width}.png` });
    }
  }
});

test('missing routes return the designed 404 and a working recovery link', async ({ page }) => {
  const response = await page.goto('/not-found');
  expect(response.status()).toBe(404);
  await expect(page.locator('h1')).toContainText('找不到了');
  await page.getByRole('link', { name: '返回首页' }).click();
  await expect(page).toHaveURL(/\/index\.html$/);
  await expect(page.locator('#hero-title')).toBeVisible();
});

import { test, expect } from '@playwright/test';

for (const prefix of ['', 'en/']) {
  test(`compatibility content stays inside its shell at every width and theme: ${prefix || 'zh'}`, async ({ page }) => {
    test.setTimeout(60000);
    await page.route('https://api.github.com/**', route => route.abort());
    await page.goto(`/${prefix}index.html#compatibility`);
    await expect(page.locator('.variant-table tbody tr')).toHaveCount(14);
    await expect(page.locator('#compatibility > :not(.shell)')).toHaveCount(0);
    for (const theme of ['light', 'dark']) {
      await page.locator('#appearance').selectOption(theme);
      for (const width of [320, 390, 768, 1024, 1440, 1920, 3840]) {
        await page.setViewportSize({ width, height: 1000 });
        const result = await page.evaluate(() => {
          const shell = document.querySelector('#compatibility > .shell');
          const bounds = shell.getBoundingClientRect();
          const padding = parseFloat(getComputedStyle(shell).paddingLeft);
          const left = bounds.left + padding;
          const right = bounds.right - padding;
          return [...shell.querySelectorAll('.variant-table-wrap, .compatibility-note, .risk-banner, .requirement-row')].map(item => {
            const box = item.getBoundingClientRect();
            return { class: item.className, inside: box.left >= left - 1 && box.right <= right + 1, aligned: Math.abs(box.left - left) < 1 };
          });
        });
        expect(result.every(item => item.inside && item.aligned), `${prefix}, ${width}, ${theme}: ${JSON.stringify(result)}`).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
    }
    for (const width of [390, 1440, 3840]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('#variant-matrix').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `.playwright/matrix-${prefix ? 'en' : 'zh'}-${width}.png` });
      await page.locator('#sms-evidence').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `.playwright/alignment-${prefix ? 'en' : 'zh'}-${width}.png` });
    }
  });

  test(`candidate instructions copy exactly and TXT files work: ${prefix || 'zh'}`, async ({ page, context, request }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    for (const variant of ['sqn100-1', 'sqn100-5', 'sqc100-1', 'sqc100-3', 'sqc100-4', 'sqc100-5', 'sqw100-1', 'sqw100-3']) {
      await page.goto(`/${prefix}trials.html#${variant}`);
      const card = page.locator(`#${variant}`);
      await expect(card.locator('details')).toHaveAttribute('open', '');
      await card.locator('[data-copy-trial]').click();
      const expected = await card.locator('.trial-message').textContent();
      // Windows clipboard reads may normalize LF to CRLF; the words and blank lines must match.
      await expect.poll(async () => (await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n')).toBe(expected);
      await expect(card.locator('[role="status"]')).toContainText(prefix ? 'Copied' : '已复制');
      const url = await card.locator('a[download]').getAttribute('href');
      const response = await request.get(new URL(url, page.url()).href);
      expect(response.status()).toBe(200);
      expect(await response.text()).toBe(expected);
    }
    await page.setViewportSize({ width: 390, height: 1000 });
    await page.locator('#sqw100-3 .trial-card-heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `.playwright/forwardable-${prefix ? 'en' : 'zh'}-390.png` });
  });
}

test('narrow compatibility table scrolls by keyboard and retains the exact-model column', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto('/index.html#variant-matrix');
  const region = page.locator('.variant-table-wrap');
  const cell = page.locator('.variant-table tbody th').first();
  const start = await cell.boundingBox();
  await region.focus();
  await region.press('ArrowRight');
  await expect.poll(() => region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  expect(Math.abs((await cell.boundingBox()).x - start.x)).toBeLessThanOrEqual(1);
});

test('copy denial and disabled scripting retain usable forwarding instructions', async ({ page, browser, baseURL }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { throw new Error('Denied'); } } }));
  await page.goto('/trials.html#sqc100-4');
  await page.locator('#sqc100-4 [data-copy-trial]').click();
  await expect(page.locator('#sqc100-4 [role="status"]')).toContainText('下载 TXT');
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL, viewport: { width: 320, height: 900 } });
  const plain = await context.newPage();
  await plain.goto('/trials.html#sqw100-1');
  await expect(plain.locator('#sqw100-1 [data-copy-trial]')).toBeHidden();
  await plain.locator('#sqw100-1 summary').click();
  await expect(plain.locator('#sqw100-1 .trial-message')).toBeVisible();
  await expect(plain.locator('#sqw100-1 a[download]')).toBeVisible();
  await context.close();
});

test('trial language switching preserves the selected model and dark hero links remain readable', async ({ page, browser, baseURL }) => {
  await page.goto('/trials.html#sqc100-3');
  await page.locator('[data-language-switch]').click();
  await expect(page).toHaveURL(/\/en\/trials\.html#sqc100-3$/);
  await expect(page.locator('#sqc100-3 details')).toHaveAttribute('open', '');
  for (const theme of ['light', 'dark']) {
    await page.locator('#appearance').selectOption(theme);
    expect(await page.locator('.guide-hero .button-secondary').evaluate(element => getComputedStyle(element).color)).toBe('rgb(237, 240, 231)');
  }
  const context = await browser.newContext({ locale: 'en-US', baseURL });
  const english = await context.newPage();
  await english.goto('/trials#sqw100-3');
  await expect(english).toHaveURL(/\/en\/trials\.html#sqw100-3$/);
  await context.close();
});

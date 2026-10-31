import { defineConfig } from '@playwright/test';

const port = process.env.BB10_TEST_PORT || '4174';
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.mjs',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: 'list',
  outputDir: '.playwright/test-results',
  use: {
    baseURL,
    channel: 'msedge',
    headless: true,
    locale: 'zh-CN',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run dev',
    url: baseURL,
    env: { PORT: port },
    reuseExistingServer: false,
    timeout: 30000,
  },
});

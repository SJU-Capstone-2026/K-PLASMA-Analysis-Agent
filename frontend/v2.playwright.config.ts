import {defineConfig} from '@playwright/test';
import {join} from 'node:path';

const port = process.env.KPLASMA_E2E_PORT ?? '5197';
const output = process.env.KPLASMA_E2E_OUTPUT ?? '/tmp/kplasma-v2-browser';
export default defineConfig({
  testDir: './e2e', testMatch: 'agent-v2-live.spec.ts', workers: 1, timeout: 480000,
  reporter: [['list']], outputDir: join(output, 'playwright'),
  use: {
    baseURL: `http://127.0.0.1:${port}`, locale: 'ko-KR', timezoneId: 'Asia/Seoul',
    viewport: {width: 1440, height: 1000}, deviceScaleFactor: 1,
    launchOptions: process.env.KPLASMA_BROWSER_EXECUTABLE
      ? {executablePath: process.env.KPLASMA_BROWSER_EXECUTABLE} : {},
  },
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`, reuseExistingServer: false,
    env: {VITE_API_TARGET: process.env.KPLASMA_E2E_API ?? 'http://127.0.0.1:8080'},
  },
});

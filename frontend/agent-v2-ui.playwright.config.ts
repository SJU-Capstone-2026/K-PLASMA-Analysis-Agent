import {defineConfig} from '@playwright/test';
import streaming from './streaming.playwright.config';

export default defineConfig(streaming, {
  testMatch: ['agent-streaming.pw.ts', 'conversation-rooms.pw.ts', 'comparison-visualization.pw.ts'],
  grepInvert: /v1 comparison charts/,
  outputDir: '/tmp/kplasma-agent-v2-ui',
});

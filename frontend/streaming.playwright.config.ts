import {defineConfig} from '@playwright/test';

export default defineConfig({
 testDir:'./src/features/agent',testMatch:'agent-streaming.pw.ts',workers:1,timeout:45000,
 expect:{timeout:8000},reporter:'list',outputDir:'/tmp/kplasma-agent-streaming-ui',
 use:{baseURL:'http://127.0.0.1:5197',viewport:{width:1440,height:1000},locale:'ko-KR',
  timezoneId:'Asia/Seoul',deviceScaleFactor:1,reducedMotion:'reduce',screenshot:'only-on-failure',
  launchOptions:process.env.KPLASMA_BROWSER_EXECUTABLE?{executablePath:process.env.KPLASMA_BROWSER_EXECUTABLE}:{}},
 webServer:{command:'npm run dev -- --port 5197 --strictPort',url:'http://127.0.0.1:5197',reuseExistingServer:false},
});

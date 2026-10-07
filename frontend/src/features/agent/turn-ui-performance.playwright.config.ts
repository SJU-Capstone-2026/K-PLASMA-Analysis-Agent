import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'.',testMatch:'turn-ui-performance.pw.ts',workers:1,reporter:'list',timeout:120000,
 outputDir:'/tmp/kplasma-turn-ui-performance',use:{baseURL:'http://127.0.0.1:5198',viewport:{width:1440,height:1000},locale:'ko-KR',timezoneId:'Asia/Seoul',deviceScaleFactor:1,
 launchOptions:process.env.KPLASMA_BROWSER_EXECUTABLE?{executablePath:process.env.KPLASMA_BROWSER_EXECUTABLE}:{},
 },webServer:{command:'npx vite --config src/features/agent/turn-ui-performance.vite.config.ts',url:'http://127.0.0.1:5198',reuseExistingServer:false}});

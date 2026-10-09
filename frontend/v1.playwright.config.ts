import {defineConfig} from '@playwright/test';
const port=process.env.KPLASMA_E2E_PORT??'5192';
/** Active v1 gate: an isolated backend, real HTTP and a running Python worker are required. */
export default defineConfig({
 testDir:'./e2e',testMatch:['agent-v1-live.spec.ts','layout-geometry.spec.ts'],workers:1,fullyParallel:false,timeout:240000,
 expect:{timeout:15000},reporter:[['list'],['json',{outputFile:`${process.env.KPLASMA_E2E_OUTPUT??'/tmp/kplasma-v1-live'}/results.json`}]],
 outputDir:process.env.KPLASMA_E2E_OUTPUT??'/tmp/kplasma-v1-live',
 use:{baseURL:`http://127.0.0.1:${port}`,locale:'ko-KR',timezoneId:'Asia/Seoul',viewport:{width:1440,height:1000},deviceScaleFactor:1,
  launchOptions:process.env.KPLASMA_BROWSER_EXECUTABLE?{executablePath:process.env.KPLASMA_BROWSER_EXECUTABLE}:{},trace:'retain-on-failure',screenshot:'only-on-failure'},
 webServer:{command:`npm run dev -- --port ${port} --strictPort`,url:`http://127.0.0.1:${port}`,reuseExistingServer:false,
  env:{VITE_API_TARGET:process.env.KPLASMA_E2E_API??'http://127.0.0.1:8080'}},
});

import {defineConfig} from '@playwright/test';
const port=process.env.KPLASMA_E2E_PORT??'5192';
export default defineConfig({
 testDir:'./e2e',testMatch:'**/*.spec.ts',workers:1,fullyParallel:false,timeout:120000,
 reporter:[['list'],['json',{outputFile:`${process.env.KPLASMA_E2E_OUTPUT}/results.json`}]],
 outputDir:process.env.KPLASMA_E2E_OUTPUT??'../backend/.runtime/verification/browser',
 use:{baseURL:`http://127.0.0.1:${port}`,locale:'ko-KR',timezoneId:'Asia/Seoul',viewport:{width:1440,height:1000},deviceScaleFactor:1,
  launchOptions:process.env.KPLASMA_BROWSER_EXECUTABLE?{executablePath:process.env.KPLASMA_BROWSER_EXECUTABLE}:{},
  trace:'retain-on-failure',screenshot:'only-on-failure'},
 webServer:{command:`npm run dev -- --port ${port} --strictPort`,url:`http://127.0.0.1:${port}`,reuseExistingServer:false,
  env:{VITE_API_TARGET:process.env.KPLASMA_E2E_API??'http://127.0.0.1:8080'}},
});

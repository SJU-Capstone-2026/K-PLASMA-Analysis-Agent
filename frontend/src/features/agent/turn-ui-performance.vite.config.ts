import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// A comparison replaces only this hook's source; imports retain their original paths.
const baseline=process.env.KPLASMA_UI_BASELINE_FILE;
const api=process.env.KPLASMA_UI_PERF_API;
const hook=resolve('src/features/agent/useConversation.ts');
export default defineConfig({plugins:[...(baseline?[{name:'turn-ui-baseline',enforce:'pre' as const,
 load(id:string){if(id===hook)return readFileSync(baseline,'utf8');},
}]:[]),react()],server:{host:'127.0.0.1',port:5198,strictPort:true,proxy:api?{'/api':{target:api,changeOrigin:true}}:undefined}});

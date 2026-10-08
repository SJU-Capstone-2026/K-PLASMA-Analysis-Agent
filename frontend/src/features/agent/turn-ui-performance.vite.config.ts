import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// A comparison replaces only this hook's source; imports retain their original paths.
const baseline=process.env.KPLASMA_UI_BASELINE_FILE;
const baselineRef=process.env.KPLASMA_UI_BASELINE_REF;
const api=process.env.KPLASMA_UI_PERF_API;
const hook=resolve('src/features/agent/useConversation.ts');
if(baseline&&baselineRef)throw new Error('Use either KPLASMA_UI_BASELINE_FILE or KPLASMA_UI_BASELINE_REF.');
const sources=new Map<string,string>();
if(baselineRef)for(const file of ['useConversation.ts','AgentPage.tsx','V1AnswerView.tsx','v1-search-model.ts']){
 sources.set(resolve(`src/features/agent/${file}`),execFileSync('git',['show',`${baselineRef}:frontend/src/features/agent/${file}`],{encoding:'utf8'}));
}
export default defineConfig({plugins:[...(baseline||baselineRef?[{name:'turn-ui-baseline',enforce:'pre' as const,
 load(id:string){if(baseline&&id===hook)return readFileSync(baseline,'utf8');return sources.get(id);},
}]:[]),react()],server:{host:'127.0.0.1',port:5198,strictPort:true,proxy:api?{'/api':{target:api,changeOrigin:true}}:undefined}});

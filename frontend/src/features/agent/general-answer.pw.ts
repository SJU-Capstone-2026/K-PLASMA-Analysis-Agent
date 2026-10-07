import {expect,test} from '@playwright/test';
import type {TurnSnapshot,WorkspaceView} from 'agent';
import wire from '../../../../agent/tests/support/answer-v2-wire.json' with {type:'json'};
import {emptyWorkspace,initialTurnUi} from './useConversation';

// Artificial prose only: these screenshots never contain experiment data or user history.
const longEquation=Array.from({length:20},(_,index)=>`n_{${index+1}}u_{${index+1}}`).join(' + ');
const markdown=`**이온 플럭스의 근사식**\n\n문장 안의 기호 $n_i$와 $u_B$를 표시합니다.\n\n$$\n\\Gamma_i \\approx n_i u_B\n$$\n\n$n_i$는 이온 밀도, $u_B$는 이온의 대표 속도를 뜻합니다.\n\n긴 수식은 수식 영역 안에서 확인할 수 있습니다.\n\n$$\n\\Gamma = ${longEquation}\n$$\n\n잘못된 수식도 뒤의 설명을 숨기지 않습니다: $\\frac{1}{$\n\n설명은 계속 표시됩니다.`;
const legacy=String.raw`저장된 답변의 기호 \(n_i\)입니다.

\[
E_i \sim eV_{\text{sheath}}
\]

기존 답변도 다시 표시됩니다.`;

for(const width of [390,800,1008,1440])test(`general answer math, legacy reload and contained overflow at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});
 await page.clock.setFixedTime(new Date('2026-10-08T00:00:00Z'));
 const errors:string[]=[];const writes:string[]=[];
 page.on('pageerror',error=>errors.push(error.message));
 const turns=[markdown,legacy].map((text,index)=>({
  id:`math-${index}`,askedAt:'2026-10-08T00:00:00Z',question:'수식 표시용 인공 질문',intent:'GENERAL_ANSWER',context:null,
  answerRunRefs:[],answerSnapshot:{...wire.general,result:{...wire.general.result,markdown:text}},ui:structuredClone(initialTurnUi),
 } satisfies TurnSnapshot));
 const workspace:WorkspaceView={...structuredClone(emptyWorkspace),conversation:{version:1,activeRun:null,turns}};
 await page.route('**/api/**',async route=>{
  const request=route.request();const path=new URL(request.url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  if(request.method()!=='GET')writes.push(path);
  if(path==='/api/runs'||path==='/api/decisions')return route.fulfill({json:[]});
  if(path==='/api/workspace')return route.fulfill({json:workspace});
  throw new Error(`Unexpected request ${request.method()} ${path}`);
 });
 await page.goto('/');
 const current=page.locator('[data-turn-id="math-0"] .v1-general-answer');
 const saved=page.locator('[data-turn-id="math-1"] .v1-general-answer');
 await expect(current.locator('.katex math')).toHaveCount(6);
 await expect(current.locator('.katex-error')).toHaveText('\\frac{1}{');
 await expect(current.getByText('설명은 계속 표시됩니다.')).toBeVisible();
 await expect(saved.locator('.katex math')).toHaveCount(2);
 await page.evaluate(()=>document.fonts.ready);
 expect(await current.locator('.katex').first().evaluate(el=>getComputedStyle(el).fontFamily)).toContain('KaTeX_Main');
 expect(await current.locator('.katex-html').first().evaluate(el=>el.getBoundingClientRect().width)).toBeGreaterThan(10);
 expect(await current.locator('.katex-mathml').first().evaluate(el=>el.getBoundingClientRect().width)).toBeLessThanOrEqual(2);
 const long=current.locator('.katex-display').last();
 expect(await long.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(true);
 await long.evaluate(el=>{el.scrollLeft=el.scrollWidth;});
 expect(await long.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(await current.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
 await page.screenshot({path:info.outputPath(`synthetic-general-math-${width}.png`),fullPage:true});
 await page.reload();
 await expect(saved.locator('.katex math')).toHaveCount(2);
 await expect(current.locator('.katex math')).toHaveCount(6);
 expect(workspace.conversation.turns[1].answerSnapshot.result).toEqual({...wire.general.result,markdown:legacy});
 expect(writes).toEqual([]);
 expect(errors).toEqual([]);
});

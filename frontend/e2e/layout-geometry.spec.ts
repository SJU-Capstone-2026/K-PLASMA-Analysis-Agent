import {expect,test} from '@playwright/test';
import {roundedOverflowRight} from './helpers';

test('CSSOM integer scrollWidth preserves fractional 530px overflow boundaries',async({page,context},info)=>{
 await page.setViewportSize({width:800,height:300});const measurements=[];
 for(const x of [356,356.125,356.25,356.484375,356.5,356.75,356.875]){
  // DOM-only fixture: no fonts, backend, graph values or workspace writes.
  await page.setContent(`<!doctype html><style>html,body{margin:0}.selector{position:absolute;left:${x}px;top:0;width:530px;height:20px}</style><div class="selector"></div>`);
  const measured=await page.evaluate(()=>{const rect=document.querySelector('.selector')!.getBoundingClientRect();return {x:rect.x,width:rect.width,right:rect.right,scrollWidth:document.documentElement.scrollWidth};});
  expect(measured.width).toBe(530);expect(measured.x).toBe(x);expect(measured.right).toBe(x+530);expect(measured.scrollWidth).toBe(roundedOverflowRight(measured.right));measurements.push(measured);
 }
 // The exact integer assertion must still expose a second, further overflow cause.
 await page.evaluate(()=>{const extra=document.createElement('div');extra.style.cssText='position:absolute;left:940px;width:10px;height:20px';document.body.append(extra);});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(950);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).not.toBe(roundedOverflowRight(measurements.at(-1)!.right));
 await info.attach('fractional-scrollwidth',{body:JSON.stringify({browser:context.browser()?.version(),viewportWidth:800,deviceScaleFactor:1,measurements,extraOverflowWidth:950}),contentType:'application/json'});
});

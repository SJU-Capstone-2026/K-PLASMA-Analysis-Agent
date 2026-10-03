import {act,render,screen} from '@testing-library/react';
import {afterEach,expect,test,vi} from 'vitest';
import {RunDetailDialog} from './RunDetail';
import {fixtureRuns} from '../../test/runs';
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
test('pending replacement hides prior version evidence even when display Run ID is unchanged',async()=>{
 const first=fixtureRuns[0],replacement={...first,runVersionId:'replacement-version'};
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith(first.runVersionId)?Promise.resolve(new Response(JSON.stringify(first))):new Promise<Response>(()=>{})));
 const {rerender}=render(<RunDetailDialog runRef={first} onClose={vi.fn()}/>);await screen.findByRole('region',{name:`${first.runId} 실험 상세`});rerender(<RunDetailDialog runRef={replacement} onClose={vi.fn()}/>);
 expect(screen.queryByRole('region')).not.toBeInTheDocument();expect(screen.getByText('검증된 Run 데이터를 불러오는 중입니다.')).toBeInTheDocument();expect(screen.queryByRole('tab')).not.toBeInTheDocument();
});
test('new immutable ref clears old error and successful replacement renders its own evidence',async()=>{
 const first=fixtureRuns[0],replacement=fixtureRuns[2];vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith(first.runVersionId)?new Response(JSON.stringify({message:'old failure'}),{status:503}):new Response(JSON.stringify(replacement))));
 const {rerender}=render(<RunDetailDialog runRef={first} onClose={vi.fn()}/>);await screen.findByRole('alert');rerender(<RunDetailDialog runRef={replacement} onClose={vi.fn()}/>);expect(screen.queryByText('old failure')).not.toBeInTheDocument();await screen.findByRole('region',{name:`${replacement.runId} 실험 상세`});expect(screen.queryByRole('alert')).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:`${replacement.runId} 실험 상세`})).toBeInTheDocument();
});
for(const late of ['success','error'])test(`late old dialog ${late} cannot overwrite the selected ref`,async()=>{
 const first=fixtureRuns[0],replacement=fixtureRuns[2];let resolveFirst!:(value:Response)=>void;vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith(first.runVersionId)?new Promise<Response>(resolve=>{resolveFirst=resolve;}):Promise.resolve(new Response(JSON.stringify(replacement)))));
 const {rerender}=render(<RunDetailDialog runRef={first} onClose={vi.fn()}/>);rerender(<RunDetailDialog runRef={replacement} onClose={vi.fn()}/>);await screen.findByRole('region',{name:`${replacement.runId} 실험 상세`});await act(async()=>resolveFirst(late==='success'?new Response(JSON.stringify(first)):new Response(JSON.stringify({message:'late failure'}),{status:503})));
 expect(screen.getByRole('region')).toHaveAttribute('aria-label',`${replacement.runId} 실험 상세`);expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

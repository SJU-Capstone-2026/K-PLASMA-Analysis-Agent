import {render,screen} from '@testing-library/react';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {ReferenceTray} from './ReferenceTray';
import {assignRunColors,RunColorsProvider,runColorStorageKey} from './RunColors';

const ids=['A','B','C','D','E','F','G','H'];
const fixed=['rgb(65, 104, 232)','rgb(10, 142, 155)','rgb(138, 91, 215)','rgb(224, 132, 42)','rgb(210, 80, 145)'];
const refs=(values:string[],version='v1')=>values.map(runId=>({runId,runVersionId:`${runId}-${version}`}));
function Harness({current=ids,history=[] as string[],scope='7.3',enabled=true,version='v1'}){
 return <RunColorsProvider key={scope} scope={scope} enabled={enabled}><div data-testid="current"><ReferenceTray references={refs(current,version)}/></div><div data-testid="history"><ReferenceTray references={refs(history)}/></div></RunColorsProvider>;
}
const colors=(tray='current')=>Array.from(screen.getByTestId(tray).querySelectorAll<HTMLElement>('.run-context-chip > i'),node=>node.style.backgroundColor);
beforeEach(()=>localStorage.clear());
afterEach(()=>vi.restoreAllMocks());

test('five fixed colors and unique later colors survive removal, versions, reorder and reload',()=>{
 const view=render(<Harness/>);const assigned=colors();
 expect(assigned.slice(0,5)).toEqual(fixed);expect(new Set(assigned).size).toBe(8);
 const random=vi.spyOn(Math,'random');const writes=vi.spyOn(Storage.prototype,'setItem');
 view.rerender(<Harness current={['H','C','A']} history={['C','H']} version="v2"/>);
 expect(colors()).toEqual([assigned[7],assigned[2],assigned[0]]);
 expect(colors('history')).toEqual([assigned[2],assigned[7]]);
 expect(random).not.toHaveBeenCalled();expect(writes).not.toHaveBeenCalled();
 view.unmount();render(<Harness current={['A','F','H']} history={['H']}/>);
 expect(colors()).toEqual([assigned[0],assigned[5],assigned[7]]);
 expect(colors('history')).toEqual([assigned[7]]);
});

test('loading placeholder cannot overwrite colors saved for the actual conversation',()=>{
 const first=render(<Harness current={['A','B','C']}/>);const assigned=colors();first.unmount();
 const saved=localStorage.getItem(runColorStorageKey);
 const view=render(<Harness current={[]} scope="0.0" enabled={false}/>);
 expect(localStorage.getItem(runColorStorageKey)).toBe(saved);
 view.rerender(<Harness current={['C','A']} scope="7.3"/>);
 expect(colors()).toEqual([assigned[2],assigned[0]]);
});

test('new conversation starts its own palette instead of reusing previous allocations',()=>{
 const view=render(<Harness/>);view.rerender(<Harness scope="7.4" current={['H','A']}/>);
 expect(colors()).toEqual(fixed.slice(0,2));
});

test('unsafe or malformed saved color preferences are ignored',()=>{
 localStorage.setItem(runColorStorageKey,JSON.stringify({version:1,scope:'7.3',entries:[['A','url(javascript:alert(1))']]}));
 const view=render(<Harness current={['A']}/>);expect(colors()).toEqual([fixed[0]]);view.unmount();
 localStorage.setItem(runColorStorageKey,'invalid JSON');
 render(<Harness current={['B']}/>);expect(colors()).toEqual([fixed[0]]);
});

test('blocked browser storage retains stable colors in the current page',()=>{
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new DOMException('Blocked');});
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('Quota');});
 const view=render(<Harness/>);const assigned=colors();
 view.rerender(<Harness current={['H','B']}/>);expect(colors()).toEqual([assigned[7],assigned[1]]);
});

test('repeated random values terminate with distinct colors and do not mutate the prior map',()=>{
 vi.spyOn(Math,'random').mockReturnValue(.3);
 const initial=new Map<string,string>();const assigned=assignRunColors(initial,ids);
 expect(initial.size).toBe(0);expect(new Set(assigned.values()).size).toBe(8);
 expect(assignRunColors(assigned,['H','A'])).toBe(assigned);
});

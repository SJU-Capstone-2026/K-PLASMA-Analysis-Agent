import {fireEvent,render,screen} from '@testing-library/react';
import {useState} from 'react';
import {expect,test} from 'vitest';
import {RunDetail} from './RunDetail';
import {fixtureRuns} from '../../test/runs';
const run=fixtureRuns[0];
test.each(['standalone','turn-owned'])('%s source disclosure closes only when the effective graph tab changes',mode=>{
 function Host(){const [tab,setTab]=useState('ied');return mode==='standalone'?<RunDetail runRef={run} run={run}/>:<RunDetail runRef={run} run={run} tab={tab} onTabChange={setTab} turnId="saved-turn"/>;}
 const {container}=render(<Host/>);let disclosure=container.querySelector('details')!;disclosure.open=true;
 fireEvent.click(screen.getByRole('tab',{name:'Ion Energy Distribution'}));expect(container.querySelector('details')).toHaveAttribute('open');
 fireEvent.click(screen.getByRole('tab',{name:'Ion Angle Distribution'}));disclosure=container.querySelector('details')!;expect(disclosure).not.toHaveAttribute('open');
 expect(screen.getByRole('tab',{name:'Ion Angle Distribution'})).toHaveAttribute('aria-selected','true');
});
test('requested unavailable tab that resolves to the same graph preserves disclosure',()=>{
 const {container,rerender}=render(<RunDetail runRef={run} run={run} tab="unknown" turnId="saved-turn"/>);container.querySelector('details')!.open=true;
 rerender(<RunDetail runRef={run} run={run} tab="ied" turnId="saved-turn"/>);expect(container.querySelector('details')).toHaveAttribute('open');
});

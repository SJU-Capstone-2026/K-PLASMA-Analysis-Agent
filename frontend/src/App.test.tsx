import {fireEvent,render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {App} from './App';
test('original shell navigates five views, keeps analysis state, and closes mobile menu',()=>{
 vi.stubGlobal('scrollTo',vi.fn());render(<App pages={{agent:()=> <p>Agent slot</p>,analysis:()=> <p>Analysis slot</p>,archive:()=> <p>Archive slot</p>,catalog:()=> <p>Catalog slot</p>}}/>);
 expect(screen.getByText('Agent slot')).toBeInTheDocument();const menu=screen.getByRole('button',{name:'메뉴 열기'});fireEvent.click(menu);expect(menu).toHaveAttribute('aria-expanded','true');
 fireEvent.click(screen.getByRole('button',{name:'실험 데이터 탐색'}));expect(screen.getByText('Analysis slot')).toBeInTheDocument();expect(menu).toHaveAttribute('aria-expanded','false');expect(document.getElementById('view-root')).toHaveFocus();fireEvent.click(screen.getByRole('button',{name:'사용 방법'}));expect(screen.getByText('세 단계로 사용하는 K-PLASMA')).toBeInTheDocument();expect(document.querySelector('.nav-tools')).toHaveAttribute('open');
 fireEvent.click(screen.getByRole('button',{name:'분석 Agent 시작'}));expect(screen.getByText('Agent slot')).toBeInTheDocument();expect(document.querySelector('.nav-tools')).not.toHaveAttribute('open');fireEvent.click(screen.getByRole('button',{name:'분석 Agent'}));expect(scrollTo).toHaveBeenCalledTimes(4);
});

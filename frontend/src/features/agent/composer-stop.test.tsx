import {act,fireEvent,render,screen} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import {RunMentionComposer} from './RunMentionComposer';

test('the composer stops a running request once without submitting a new question',async()=>{
 let finish!:()=>void;
 const onStop=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
 const submit=vi.fn();
 const props={text:'다음 질문',onText:vi.fn(),add:async()=>true,disabled:true};
 const {rerender}=render(<form onSubmit={submit}><RunMentionComposer {...props} onStop={onStop}/></form>);
 const stop=screen.getByRole('button',{name:'분석 중지'});
 expect(screen.queryByRole('button',{name:'분석'})).not.toBeInTheDocument();
 fireEvent.click(stop);fireEvent.click(stop);
 expect(onStop).toHaveBeenCalledOnce();
 expect(stop).toBeDisabled();
 expect(submit).not.toHaveBeenCalled();
 await act(async()=>finish());
 rerender(<form onSubmit={submit}><RunMentionComposer {...props} disabled={false}/></form>);
 expect(screen.queryByRole('button',{name:'분석 중지'})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'분석'})).toBeEnabled();
 expect(screen.getByRole('textbox')).toHaveValue('다음 질문');
});

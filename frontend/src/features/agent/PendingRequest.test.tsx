import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,test,vi} from 'vitest';
import type {AgentRequestView} from 'agent';
import {PendingRequest} from './PendingRequest';
const request:AgentRequestView={requestId:'r1',requestRevision:2,status:'NEEDS_INPUT',stage:'decide',graphVersion:'v1',question:'두 Run을 비교해줘',pendingInput:{id:'p1',message:'기준 Run을 알려 주세요.'},error:null,partialResult:null,turnId:null,answerSnapshot:null,inputEvents:[{input:{text:'에너지를 비교해줘'}}]};
test('clarification retains history and submits text safely within the same request',async()=>{const resume=vi.fn(async()=>{});render(<PendingRequest request={request} sending={false} onResume={resume} onCancel={async()=>{}} onError={()=>{}}/>);expect(screen.getByText('추가 입력: 에너지를 비교해줘')).toBeInTheDocument();fireEvent.change(screen.getByRole('textbox',{name:'기준 Run을 알려 주세요.'}),{target:{value:'<script>Run A</script>'}});fireEvent.click(screen.getByRole('button',{name:'답변하고 계속'}));await waitFor(()=>expect(resume).toHaveBeenCalledWith({text:'<script>Run A</script>'}));expect(document.querySelector('script')).toBeNull();});
test('failed explanation only exposes verified comparison and never renders arbitrary draft',()=>{const failed={...request,status:'FAILED',error:{code:'MODEL_UNAVAILABLE',message:'설명 모델에 연결할 수 없습니다.'},partialResult:{kind:'compare_runs',resultStatus:'COMPARISON_READY',baseline:{runId:'A',runVersionId:'va'},target:{runId:'B',runVersionId:'vb'},conditions:[],metrics:[],changedConditions:[]},draft:'UNVERIFIED SECRET DRAFT'};render(<PendingRequest request={failed as AgentRequestView} sending={false} onResume={async()=>{}} onCancel={async()=>{}} onError={()=>{}}/>);expect(screen.getByText('비교 완료 / 설명 실패')).toBeInTheDocument();expect(screen.queryByText('UNVERIFIED SECRET DRAFT')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'분석 취소'})).not.toBeInTheDocument();});

test('choosing an option clears typed text before the next clarification',async()=>{
 const resume=vi.fn(async()=>{});const props={sending:false,onResume:resume,onCancel:async()=>{},onError:()=>{}};
 const first={...request,pendingInput:{...request.pendingInput!,options:[{label:'RUN-A 선택',input:{runId:'RUN-A'}}]}};
 const {rerender}=render(<PendingRequest {...props} request={first}/>);
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'보내지 않을 초안'}});
 fireEvent.click(screen.getByRole('button',{name:'RUN-A 선택'}));
 await waitFor(()=>expect(screen.getByRole('textbox')).toHaveValue(''));
 fireEvent.change(screen.getByRole('textbox'),{target:{value:'이전 질문의 초안'}});
 rerender(<PendingRequest {...props} request={{...request,pendingInput:{id:'p2',message:'비교할 Run을 알려 주세요.'}}}/>);
 expect(screen.getByRole('textbox',{name:'비교할 Run을 알려 주세요.'})).toHaveValue('');
});

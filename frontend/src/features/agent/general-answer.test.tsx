import {render,screen} from '@testing-library/react';
import {expect,test} from 'vitest';
import {GeneralAnswerCard} from './GeneralAnswerCard';
test('general answer renders Markdown without executing HTML and preserves formulas',()=>{
 const {container}=render(<GeneralAnswerCard result={{kind:'generate_answer',resultStatus:'ANSWER_READY',knowledgeBasis:'LLM_GENERAL_KNOWLEDGE',usedRunRefs:[],markdown:'**평균 에너지**는 분포의 평균입니다.\n\n`E = 1/2 mv²`\n\n<script>alert(1)</script>\n\n[위험](javascript:alert(1))'}}/>);
 expect(screen.getByText('평균 에너지').tagName).toBe('STRONG');
 expect(screen.getByText('E = 1/2 mv²')).toBeInTheDocument();
 expect(container.querySelector('script,img,[onerror],a[href^="javascript:"]')).toBeNull();
});

import {render,screen} from '@testing-library/react';
import type {GeneralAnswerResult} from 'agent';
import {expect,test} from 'vitest';
import {GeneralAnswerCard} from './GeneralAnswerCard';
test('general answer renders Markdown without executing HTML and preserves code',()=>{
 const {container}=render(<GeneralAnswerCard result={{kind:'generate_answer',resultStatus:'ANSWER_READY',knowledgeBasis:'LLM_GENERAL_KNOWLEDGE',usedRunRefs:[],markdown:'**평균 에너지**는 분포의 평균입니다.\n\n`E = 1/2 mv²`\n\n<script>alert(1)</script>\n\n[위험](javascript:alert(1))'}}/>);
 expect(screen.getByText('평균 에너지').tagName).toBe('STRONG');
 expect(screen.getByText('E = 1/2 mv²')).toBeInTheDocument();
 expect(container.querySelector('script,img,[onerror],a[href^="javascript:"]')).toBeNull();
});

function answer(markdown:string):GeneralAnswerResult{
 return {kind:'generate_answer',resultStatus:'ANSWER_READY',knowledgeBasis:'LLM_GENERAL_KNOWLEDGE',usedRunRefs:[],markdown};
}

test('general answer typesets inline symbols and a display equation',()=>{
 const {container}=render(<GeneralAnswerCard result={answer('이온 밀도는 $n_i$입니다. 분수 $\\frac{n_i}{u_B}$도 표시합니다.\n\n$$\n\\Gamma_i \\approx n_i u_B\n$$\n\n기호의 뜻을 설명합니다.')}/>);
 expect(container.querySelectorAll('.katex math')).toHaveLength(3);
 expect(container.querySelectorAll('.katex-display')).toHaveLength(1);
 expect(container.querySelector('math msub')).not.toBeNull();
 expect(container.querySelector('math mfrac')).not.toBeNull();
 expect([...container.querySelectorAll('annotation')].map(node=>node.textContent)).toEqual(['n_i','\\frac{n_i}{u_B}','\\Gamma_i \\approx n_i u_B']);
 expect(screen.getByText('기호의 뜻을 설명합니다.')).toBeInTheDocument();
});

test('saved answers with backslash delimiters typeset without rewriting the answer',()=>{
 const result=Object.freeze(answer(String.raw`이온 밀도는 \(n_i\)입니다.

\[
E_i \sim eV_{\text{sheath}}
\]

이어서 설명합니다.`));
 const {container}=render(<GeneralAnswerCard result={result}/>);
 expect(container.querySelectorAll('.katex math')).toHaveLength(2);
 expect(container.querySelectorAll('.katex-display')).toHaveLength(1);
 expect([...container.querySelectorAll('annotation')].map(node=>node.textContent)).toEqual(['n_i','E_i \\sim eV_{\\text{sheath}}']);
 expect(result.markdown).toContain('\\[\nE_i');
});

test('backslash compatibility leaves Markdown code, links and ordinary brackets intact',()=>{
 const markdown=[
  String.raw`문장 속 \(n_i\)만 수식입니다.`,
  '인라인 코드: `\\(literal\\)`',
  '````text\n```\n\\[fenced\\]\n````',
  '    \\[indented\\]',
  '> `\\(quoted code\\)`',
  String.raw`[문서](https://example.com/\(literal\))`,
  String.raw`일반 [대괄호]와 \\[escaped\\]입니다.`,
 ].join('\n\n');
 const {container}=render(<GeneralAnswerCard result={answer(markdown)}/>);
 expect(container.querySelectorAll('.katex math')).toHaveLength(1);
 expect([...container.querySelectorAll('code')].map(node=>node.textContent)).toEqual(['\\(literal\\)','```\n\\[fenced\\]\n','\\[indented\\]\n','\\(quoted code\\)']);
 expect(screen.getByRole('link',{name:'문서'})).toHaveAttribute('href','https://example.com/(literal)');
 expect(screen.getByText('일반 [대괄호]와 \\[escaped\\]입니다.')).toBeInTheDocument();
});

test('invalid math retains its source and does not hide the rest of the answer',()=>{
 const {container}=render(<GeneralAnswerCard result={answer('설명 시작.\n\n$\\frac{1}{$\n\n설명 계속.\n\n$E_i$')}/>);
 expect(container.querySelector('.katex-error')).toHaveTextContent('\\frac{1}{');
 expect(screen.getByText('설명 계속.')).toBeInTheDocument();
 expect(container.querySelectorAll('.katex math')).toHaveLength(1);
});

test('math support does not enable raw HTML or trusted TeX commands',()=>{
 const {container}=render(<GeneralAnswerCard result={answer(String.raw`$\href{javascript:alert(1)}{unsafe}$

$\htmlClass{injected}{x}$

<img src="x" onerror="alert(1)">

<script>alert(1)</script>`)}/>);
 expect(container.querySelector('script,img,[onerror],a[href^="javascript:"],.injected')).toBeNull();
});

test.each(['**Ar⁺**는 양이온 표기입니다.','주로 **Ar⁺**가 표시됩니다.','**e⁻**는 전자 표기입니다.','**압력(mTorr)**는 단위를 포함합니다.'])(
 'saved answer renders emphasis next to Korean without exposing markers: %s',markdown=>{
  const result=Object.freeze(answer(markdown));
  const {container}=render(<GeneralAnswerCard result={result}/>);
  expect(container.querySelector('strong')).not.toBeNull();
  expect(container.textContent).not.toContain('**');
  expect(container.textContent).toContain(markdown.replaceAll('**',''));
  expect(result.markdown).toBe(markdown);
 });

test('Korean emphasis preserves inline math, legacy math and nested emphasis',()=>{
 const result=Object.freeze(answer(String.raw`**$\mathrm{Ar}^{+}$**는 기호입니다.

**\(\mathrm{Ar}_{2}^{+}\)**는 다른 기호입니다.

**전하 *+***는 강조 예시입니다.`));
 const {container}=render(<GeneralAnswerCard result={result}/>);
 expect(container.querySelectorAll('strong')).toHaveLength(3);
 expect(container.querySelectorAll('strong .katex math')).toHaveLength(2);
 expect(container.querySelector('strong em')).toHaveTextContent('+');
 expect(container.textContent).not.toContain('**');
 expect(result.markdown).toContain('**\\(\\mathrm{Ar}_{2}^{+}\\)**는');
});

test('Korean emphasis leaves escaped markers, code, links and formula source untouched',()=>{
 const markdown=[
  String.raw`\*\*Ar⁺\*\*는 그대로 표시합니다.`,
  '코드: `**Ar⁺**는`',
  '~~~text\n**Ar⁺**는\n~~~',
  '[기호 문서](https://example.com/**Ar⁺**)',
  '$x^{**}$',
  '~~기존 취소선~~',
 ].join('\n\n');
 const {container}=render(<GeneralAnswerCard result={answer(markdown)}/>);
 expect(screen.getByText('**Ar⁺**는 그대로 표시합니다.')).toBeInTheDocument();
 expect([...container.querySelectorAll('code')].map(el=>el.textContent)).toEqual(['**Ar⁺**는','**Ar⁺**는\n']);
 expect(screen.getByRole('link',{name:'기호 문서'})).toHaveAttribute('href','https://example.com/**Ar%E2%81%BA**');
 expect(container.querySelector('annotation')).toHaveTextContent('x^{**}');
 expect(container.querySelector('del')).toHaveTextContent('기존 취소선');
 expect(container.querySelector('strong')).toBeNull();
});

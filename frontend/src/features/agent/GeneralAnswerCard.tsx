import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkCjkFriendly from 'remark-cjk-friendly/parseOnly';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import type {GeneralAnswerResult} from 'agent';
import {normalizeLegacyMath} from './math-markdown';

export function GeneralAnswerCard({result}:{result:GeneralAnswerResult}){
 return <section className="v1-general-answer"><span className="eyebrow">LLM 일반 지식 기반</span><div className="v1-markdown"><Markdown remarkPlugins={[remarkGfm,remarkCjkFriendly,remarkMath]} rehypePlugins={[[rehypeKatex,{trust:false,strict:'ignore',errorColor:'#6b5872'}]]} skipHtml>{normalizeLegacyMath(result.markdown)}</Markdown></div></section>;
}

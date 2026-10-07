import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {GeneralAnswerResult} from 'agent';

export function GeneralAnswerCard({result}:{result:GeneralAnswerResult}){
 return <section className="v1-general-answer"><span className="eyebrow">LLM 일반 지식 기반</span><div className="v1-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml>{result.markdown}</Markdown></div></section>;
}

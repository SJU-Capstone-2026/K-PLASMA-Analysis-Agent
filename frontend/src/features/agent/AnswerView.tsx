import {lazy, Suspense} from 'react';
import {isCompositeAnswerSnapshot,isV1AnswerSnapshot,type TurnSnapshot} from 'agent';
import {V1AnswerView} from './V1AnswerView';
import {V2AnswerView} from './V2AnswerView';
import {PrototypeAnswerMarkup,type AnswerAction} from './PrototypeAnswerMarkup';
export type {AnswerAction} from './PrototypeAnswerMarkup';

const AnswerMarkdown = lazy(() => import('./GeneralAnswerCard').then(module => ({default: module.AnswerMarkdown})));

export function AnswerView({turn,onAction}:{turn:TurnSnapshot;onAction:AnswerAction}) {
 const snapshot = turn.answerSnapshot;
 if (isCompositeAnswerSnapshot(snapshot)) return <V2AnswerView answer={snapshot} turn={turn} onAction={onAction}/>;
 if (isV1AnswerSnapshot(snapshot)) return <V1AnswerView turn={turn} onAction={onAction}/>;
 if (snapshot.graphVersion === 'v3' && snapshot.implementationId === 'v3' &&
     snapshot.schemaVersion === 1 && typeof snapshot.answer === 'string') {
  return <div className="agent-v2-answer">
   <Suspense fallback={<p role="status">답변을 표시하고 있습니다.</p>}>
    <AnswerMarkdown markdown={snapshot.answer} preserveHtmlText/>
   </Suspense>
  </div>;
 }
 return <PrototypeAnswerMarkup answer={snapshot} turn={turn} onAction={onAction}/>;
}

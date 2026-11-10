import {isGraphV2AnswerSnapshot,isV1AnswerSnapshot,type TurnSnapshot} from 'agent';
import {V1AnswerView} from './V1AnswerView';
import {V2AnswerView} from './V2AnswerView';
import {PrototypeAnswerMarkup,type AnswerAction} from './PrototypeAnswerMarkup';
export type {AnswerAction} from './PrototypeAnswerMarkup';
export function AnswerView({turn,onAction}:{turn:TurnSnapshot;onAction:AnswerAction}){if(isGraphV2AnswerSnapshot(turn.answerSnapshot))return <V2AnswerView answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;return isV1AnswerSnapshot(turn.answerSnapshot)?<V1AnswerView turn={turn} onAction={onAction}/>:<PrototypeAnswerMarkup answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;}

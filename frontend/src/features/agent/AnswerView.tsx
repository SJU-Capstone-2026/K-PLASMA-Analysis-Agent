import {isV1AnswerSnapshot,type TurnSnapshot} from 'agent';
import {V1AnswerView} from './V1AnswerView';
import {PrototypeAnswerMarkup,type AnswerAction} from './PrototypeAnswerMarkup';
export type {AnswerAction} from './PrototypeAnswerMarkup';
export function AnswerView({turn,onAction}:{turn:TurnSnapshot;onAction:AnswerAction}){return isV1AnswerSnapshot(turn.answerSnapshot)?<V1AnswerView turn={turn} onAction={onAction}/>:<PrototypeAnswerMarkup answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;}

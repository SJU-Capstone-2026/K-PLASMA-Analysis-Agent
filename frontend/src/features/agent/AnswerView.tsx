import {isGraphV2AnswerSnapshot,isGraphV3AnswerSnapshot,isV1AnswerSnapshot,type TurnSnapshot} from 'agent';
import {V1AnswerView} from './V1AnswerView';
import {V2AnswerView} from './V2AnswerView';
import {V3AnswerView} from './V3AnswerView';
import {PrototypeAnswerMarkup,type AnswerAction} from './PrototypeAnswerMarkup';
export type {AnswerAction} from './PrototypeAnswerMarkup';
export function AnswerView({turn,onAction}:{turn:TurnSnapshot;onAction:AnswerAction}){if(isGraphV3AnswerSnapshot(turn.answerSnapshot))return <V3AnswerView answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;if(isGraphV2AnswerSnapshot(turn.answerSnapshot))return <V2AnswerView answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;return isV1AnswerSnapshot(turn.answerSnapshot)?<V1AnswerView turn={turn} onAction={onAction}/>:<PrototypeAnswerMarkup answer={turn.answerSnapshot} turn={turn} onAction={onAction}/>;}

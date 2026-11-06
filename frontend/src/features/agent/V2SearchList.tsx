import {useState} from 'react';
import type {RunSummary} from 'agent';
import {measurementText, metricNames, numberText, reverseSearchCriteria, type SearchResult} from './agent-contract';
import type {AnswerAction} from './PrototypeAnswerMarkup';

const conditions = ['pressure', 'sourcePower', 'biasPower'] as const;
const outputs = ['ionFlux', 'meanIonEnergy', 'iedWidth'] as const;
type Field = typeof conditions[number] | typeof outputs[number];
const fields: readonly Field[] = [...conditions, ...outputs];
const pageSize = 10;

export function V2SearchList({result, runs, onAction, readOnly=false}: {
  result: SearchResult;
  runs: RunSummary[];
  onAction?: AnswerAction;
  readOnly?: boolean;
}) {
  const [page, setPage] = useState(0);
  const forward = result.kind === 'forward_lookup';
  const showActions = !readOnly && !!onAction;
  const requested = new Set([
    ...(result.constraints ?? []).map(rule => rule.metric),
    ...(result.goals ?? []).map(goal => goal.metric),
  ]);
  const columns = forward ? fields : fields.filter(field => requested.has(field));
  const shown = columns.length ? columns : outputs;
  const first = page * pageSize;
  const pageCount = Math.ceil(runs.length / pageSize);
  const criteria = forward
    ? conditions.flatMap(key => {
      const value = result.requestedConditions?.[key];
      return value === undefined ? [] : [`${metricNames[key]} ${value} ${key === 'pressure' ? 'mTorr' : 'W'}`];
    })
    : reverseSearchCriteria(result);

  return <section className="v2-result-list">
    {criteria.length > 0 && <p>{criteria.join(' · ')}</p>}
    {result.resultStatus === 'NEAREST_ONLY' && <p>정확히 일치하는 Run이 없어 가장 가까운 Run을 표시합니다.</p>}
    {runs.length === 0 ? <p>조건에 맞는 Run이 없습니다.</p> : <>
      <div className="v1-table-scroll" tabIndex={0}>
        <table className="v1-comparison-table" aria-label="검색 Run 목록">
          <thead><tr>
            <th scope="col">Run</th>
            {shown.map(field => <th scope="col" key={field}>{metricNames[field]}</th>)}
            {showActions && <th scope="col">작업</th>}
          </tr></thead>
          <tbody>{runs.slice(first, first + pageSize).map(run => <tr key={run.runVersionId}>
            <th scope="row">{run.runId}</th>
            {shown.map(field => {
              const value = field in run.metrics ? run.metrics[field as typeof outputs[number]] : run[field as typeof conditions[number]];
              return <td key={field}>{value == null ? '—' : measurementText(numberText(value),run.units[field] ?? '')}</td>;
            })}
            {showActions && <td className="v2-row-actions">
              {([
                ['continue-with-run', '채팅에 추가'],
                ['open-run-detail', '상세'],
                ['open-v2-step-record', '판단 기록'],
              ] as const).map(([name, label]) =>
                <button key={name} className="button button--ghost button--small" type="button"
                  data-run-id={run.runId} data-run-version-id={run.runVersionId}
                  aria-label={`${run.runId} ${label}`}
                  onClick={event => onAction?.(name, event.currentTarget)}>{name === 'continue-with-run' ? '+' : label}</button>)}
            </td>}
          </tr>)}</tbody>
        </table>
      </div>
      {pageCount > 1 && <div className="agent-page-actions v2-result-pages" aria-label="검색 목록 페이지">
        <button type="button" className="button button--ghost button--small" disabled={page === 0}
          onClick={() => setPage(page - 1)}>이전</button>
        <span>{first + 1}–{Math.min(first + pageSize, runs.length)} / {runs.length}개</span>
        <button type="button" className="button button--ghost button--small" disabled={page + 1 === pageCount}
          onClick={() => setPage(page + 1)}>다음</button>
      </div>}
    </>}
  </section>;
}

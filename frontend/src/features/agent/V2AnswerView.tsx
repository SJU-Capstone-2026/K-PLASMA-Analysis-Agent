import {lazy, Suspense} from 'react';
import type {ComparisonResultV2, GraphV2AnswerSnapshotV1, Snapshot, TurnSnapshot} from 'agent';
import {searchGroups, snapshotResult, type SearchResult} from './agent-contract';
import type {AnswerAction} from './PrototypeAnswerMarkup';
import {hasOnlyExpectedOutputGaps, RunComparisonCard} from './RunComparisonCard';
import {V2SearchList} from './V2SearchList';

const AnswerMarkdown = lazy(() => import('./GeneralAnswerCard').then(module => ({default: module.AnswerMarkdown})));

const titles = {
  forward_lookup: '조건 조회 결과',
  reverse_search: '후보 검색 결과',
  compare_runs: 'Run 비교 결과',
};

export function V2AnswerView({answer, turn, onAction}: {
  answer: GraphV2AnswerSnapshotV1;
  turn: TurnSnapshot;
  onAction: AnswerAction;
}) {
  const toolSteps = answer.stepResults.flatMap(step => {
    const result = step.outputs.toolResult;
    if (!result || typeof result !== 'object' || Array.isArray(result) ||
        typeof result.kind !== 'string' || !Object.hasOwn(titles, result.kind)) return [];
    return [{step, result: result as Snapshot, kind: result.kind as keyof typeof titles}];
  });
  const last = toolSteps.at(-1);
  const comparison = last?.kind === 'compare_runs' && Array.isArray(last.result.metricIds) && Array.isArray(last.result.runs)
    ? last.result as unknown as ComparisonResultV2 : undefined;
  const iadMetrics = comparison?.metricIds.filter(metric => metric.startsWith('iad.')) ?? [];
  const iadRunCount = comparison?.runs.filter(run =>
    iadMetrics.some(metric => run.metrics[metric]?.status === 'AVAILABLE')).length ?? 0;
  const interpretations = Array.isArray(answer.draft?.interpretations) ? answer.draft.interpretations.flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || typeof item.text !== 'string') return [];
    const assumptions = Array.isArray(item.assumptions)
      ? item.assumptions.filter(value => typeof value === 'string') : [];
    return [{text: item.text, assumptions}];
  }) : [];
  const limitations = Array.isArray(answer.draft?.limitations) ? answer.draft.limitations.flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || typeof item.text !== 'string') return [];
    // Older answers could mistake the writer's compact evidence for the actual comparison table.
    if (iadRunCount > 0 && item.text.includes('Run별 IAD 값이 아니라') && item.text.includes('요약만 포함되어 있어')) return [];
    return [item.text];
  }) : [];
  const comparedVersions = new Set(last?.kind === 'compare_runs' ? last.step.runRefs.map(ref => ref.runVersionId) : []);
  const incomplete = answer.hasIncompleteWork ?? (
    answer.stepResults.some(step => ['partial', 'blocked', 'failed'].includes(step.status)) ||
    answer.budget.partial_finalizations_used > 0 ||
    (answer.executionStatus === 'PARTIAL' && answer.draft !== null)
  );
  const partialSteps = answer.stepResults.filter(step => step.status === 'partial');
  const expectedOutputGaps = incomplete && partialSteps.length > 0 && answer.executionStatus !== 'FAILED' &&
    answer.budget.partial_finalizations_used === 0 &&
    !answer.stepResults.some(step => step.status === 'blocked' || step.status === 'failed') &&
    partialSteps.every(step => toolSteps.some(item => item.step === step && item.kind === 'compare_runs' &&
      hasOnlyExpectedOutputGaps(item.result as unknown as ComparisonResultV2)));
  const renderTool = ({step, result, kind}: typeof toolSteps[number]) => {
    const action: AnswerAction = (name, element) => {
      element.dataset.executionId = step.executionId;
      element.dataset.stepId = step.stepId;
      element.dataset.groupId = kind === 'compare_runs' ? 'comparison' : 'common';
      onAction(name, element);
    };
    if (kind === 'compare_runs') {
      const isIead = Array.isArray(result.plotIds) && result.plotIds.includes('iead');
      return <RunComparisonCard key={step.executionId} compact storageId={isIead ? `${turn.id}:${step.executionId}` : turn.id}
        result={result as unknown as ComparisonResultV2} onAction={action}/>;
    }
    const search = snapshotResult<SearchResult>({result});
    return <V2SearchList result={search} runs={searchGroups(search)[0]?.runs ?? []} onAction={action}/>;
  };

  return <div className="agent-v2-answer">
    {last ? <>
      <section aria-label={titles[last.kind]} data-execution-id={last.step.executionId}>
        {last.kind !== 'compare_runs' && <h3>{titles[last.kind]}</h3>}
        {renderTool(last)}
      </section>
      {(interpretations.length > 0 || limitations.length > 0) && <section className="v2-answer-explanation" aria-label="결과 해석">
        <Suspense fallback={<p role="status">해석을 표시하고 있습니다.</p>}>
          {interpretations.map((item,index) => <div key={index}>
            <AnswerMarkdown markdown={item.text} preserveHtmlText/>
            {item.assumptions.length > 0 && <ul className="v2-answer-assumptions" aria-label="해석의 전제">
              {item.assumptions.map((text,position) => <li key={position}><AnswerMarkdown markdown={text} preserveHtmlText/></li>)}
            </ul>}
          </div>)}
          {limitations.map((text,index) => <div key={index} className="v1-limitation"><AnswerMarkdown markdown={text} preserveHtmlText/></div>)}
        </Suspense>
      </section>}
      {iadRunCount > 0 && <p className="v1-limitation">IAD 값이 있는 {iadRunCount}개 Run의 개별 값은 위 비교 표에서 확인할 수 있어요.</p>}
      {incomplete && !expectedOutputGaps && <p>요청의 일부를 처리하지 못했습니다. 확인된 결과를 표시합니다.</p>}
      {toolSteps.slice(0, -1).map(item => {
        const candidates = item.kind === 'reverse_search' ? searchGroups(snapshotResult<SearchResult>({result:item.result}))[0]?.runs : undefined;
        const sameRuns = !!candidates?.length && candidates.length === comparedVersions.size
          && candidates.every(run => comparedVersions.has(run.runVersionId));
        return <details key={item.step.executionId} className="v1-interpretation" data-execution-id={item.step.executionId}>
          <summary>{sameRuns ? `검색 근거 · ${candidates.length}개` : titles[item.kind]}</summary>
          {renderTool(item)}
        </details>;
      })}
    </> : answer.intent === 'GENERAL_ANSWER' ? <Suspense fallback={<p role="status">답변을 표시하고 있습니다.</p>}>
      <AnswerMarkdown markdown={answer.answer} preserveHtmlText/>
    </Suspense> : <div className="agent-v2-text" style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{answer.answer}</div>}
  </div>;
}

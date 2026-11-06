import {expect, test, type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import type {AgentRequestView, GraphVersion, RunSummary, WorkspaceView} from 'agent';

const api = process.env.KPLASMA_E2E_API;
const output = process.env.KPLASMA_E2E_OUTPUT;
if (!api || !output) throw new Error('An isolated artificial-data backend and output directory are required.');

const cases = [
  {id: 'concept', question: 'IED가 뭐야? 이온 에너지 분포라는 개념을 간단히 설명해줘.'},
  {id: 'strict-search', question: '이온 플럭스가 40보다 높은 실제 Run을 모두 찾아줘.'},
  {id: 'nested', question: '비교할 두 Run은 내가 고를게. 선택한 두 Run 모두보다 이온 플럭스가 높은 후보를 찾아줘.'},
];

async function ask(page: Page, text: string): Promise<AgentRequestView> {
  await page.getByRole('textbox', {name: '공정 데이터에 질문하기'}).fill(text);
  const accepted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/agent/requests'
    && r.request().method() === 'POST');
  await page.locator('#agent-query-form [type="submit"]').click();
  const response = await accepted;
  expect([200, 202]).toContain(response.status());
  return response.json();
}

async function terminal(page: Page, id: string, revision = 0): Promise<AgentRequestView> {
  let result!: AgentRequestView;
  await expect.poll(async () => {
    const response = await page.request.get(`${api}/api/agent/requests/${id}`);
    result = await response.json();
    return result.requestRevision >= revision ? result.status : 'WAITING';
  }, {timeout: 100000, intervals: [300, 1000]}).toMatch(/COMPLETED|NEEDS_INPUT|FAILED|CANCELLED/);
  return result;
}

async function pick(page: Page, runs: RunSummary[]) {
  const rows = page.locator('.v1-run-selection');
  for (const run of runs) {
    await rows.getByRole('checkbox', {name: new RegExp(run.runId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))}).check();
  }
  const baseline = rows.getByLabel(/비교 기준/);
  if (await baseline.count()) {
    if (!await baseline.isVisible()) await rows.getByText('선택 옵션', {exact: true}).click();
    const values = await baseline.first().locator('option').evaluateAll(items =>
      items.map(item => (item as HTMLOptionElement).value).filter(Boolean));
    if (values.length) await baseline.first().selectOption(values[0]);
  }
  await page.getByRole('button', {name: '선택한 실험으로 계속'}).click();
}

for (const graphVersion of ['v1', 'v2'] satisfies GraphVersion[]) {
  test(`${graphVersion} browser answers`, async ({page}) => {
    const allRuns = await (await page.request.get(`${api}/api/runs`)).json() as RunSummary[];
    const runs = allRuns.filter(run => run.catalogStatus === 'READY').sort((a, b) => a.metrics.ionFlux - b.metrics.ionFlux);
    expect(runs.length).toBeGreaterThanOrEqual(2);
    const selected = runs.slice(0, 2);
    const expected = runs.filter(run => run.metrics.ionFlux > Math.max(...selected.map(r => r.metrics.ionFlux)))
      .map(r => r.runId).sort();
    const rows = [];
    for (const item of cases) {
      const before = await (await page.request.get(`${api}/api/workspace`)).json() as WorkspaceView;
      await page.request.post(`${api}/api/workspace/new-conversation`, {data: {stateToken: before.stateToken}});
      await page.goto('/?view=agent');
      const selector = page.getByRole('combobox', {name: 'Agent 버전'});
      await expect(selector).toBeEnabled();
      await selector.selectOption(graphVersion);
      const accepted = await ask(page, item.question);
      let result = await terminal(page, accepted.requestId);
      if (item.id === 'nested' && result.status === 'NEEDS_INPUT' && result.pendingInput?.type === 'run_selection') {
        await pick(page, selected);
        result = await terminal(page, accepted.requestId, result.requestRevision + 1);
      }
      const snapshot = result.answerSnapshot as Record<string, unknown> | null;
      const steps = (snapshot?.stepResults ?? []) as {outputs: {toolResult?: {kind?: string; commonRunIds?: string[]}}}[];
      const search = graphVersion === 'v2' ? [...steps].reverse().find(s => s.outputs.toolResult?.kind === 'reverse_search')?.outputs.toolResult
        : snapshot?.result as {kind?: string; commonRunIds?: string[]} | undefined;
      const actual = [...(search?.commonRunIds ?? [])].sort();
      const strictExpected = runs.filter(run => run.metrics.ionFlux > 40).map(run => run.runId).sort();
      let issue: string | null = null;
      if (result.status !== 'COMPLETED') issue = result.error?.code ?? result.status;
      else if (item.id === 'concept' && snapshot?.intent !== 'GENERAL_ANSWER' && snapshot?.kind !== 'generate_answer') issue = '일반 개념 경로 오분류';
      else if (item.id !== 'concept' && (search?.kind !== 'reverse_search'
          || JSON.stringify(actual) !== JSON.stringify(item.id === 'nested' ? expected : strictExpected))) {
        issue = '요청한 검색 또는 예상 후보가 누락됨';
      }
      if (process.env.KPLASMA_V2_MOCK === 'true') expect.soft(issue, item.id).toBeNull();
      const activities = result.executionSummary?.activities ?? [];
      if (process.env.KPLASMA_V2_MOCK === 'true' && graphVersion === 'v2') {
        const planReviews = activities.filter(a => a.code === 'PLAN_REVIEW' && a.phase === 'started');
        expect.soft(planReviews, `${item.id}: structured HITL must reuse its plan review`)
          .toHaveLength(item.id === 'concept' ? 0 : 1);
        expect.soft(activities.filter(a => a.code === 'REVIEW'), `${item.id}: no experimental interpretation`).toHaveLength(0);
      }
      const answer = page.locator('.agent-response').last();
      const visible = result.status === 'COMPLETED' ? await answer.innerText({timeout: 12000})
        : await page.locator('.agent-page').innerText();
      rows.push({id: item.id, question: item.question, graphVersion, pass: issue === null,
        issue, status: result.status, visible, actual, snapshot, activities,
        expected: item.id === 'nested' ? expected : strictExpected});
      await writeFile(join(output!, `${graphVersion}-answers.json`), JSON.stringify(rows, null, 2));
      if (result.status === 'COMPLETED') {
        for (const width of [390, 800, 1008, 1440]) {
          await page.setViewportSize({width, height: 1000});
          const widthOk = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
          expect.soft(widthOk, `page must not overflow at ${width}px`).toBe(true);
          await page.screenshot({path: join(output!, `${graphVersion}-${item.id}-${width}.png`)});
        }
      }
    }
  });
}

# Agent Graph v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 v1을 보존하면서, 새 대화에서 선택하는 v2가 여러 도구의 결과를 연결·검증·재계획하고 출처가 유지된 복합 답변을 제공하게 한다.

**Architecture:** 공유 계약을 먼저 고정하고 서버의 대화 버전·단계 실행 기록을 추가한 뒤 Python의 계획 검사·참조 해석·순차 실행·답변 검증을 연결한다. LangGraph의 외부 제어 흐름은 코드로 고정하고 LLM은 `submit_plan`으로 계획 데이터를 제출한다. 마지막으로 v2 전용 답변·중간 결과·기록 UI와 모의 통합 검증·실제 모델 평가를 붙인다.

**Tech Stack:** 기존 프레임워크·SDK의 잠금 버전을 유지한다. Node `22.23.3`, npm `>=10 <12`, TypeScript/React/Vite/Vitest/Playwright, Java 21·Spring Boot `4.1.1`·PostgreSQL/Flyway, Python `>=3.12,<3.14`·uv·LangGraph `>=1.0,<2`·Pydantic `>=2.10,<3`·OpenAI `>=2,<3`·httpx `>=0.28,<1`. 현재 `uv.lock`의 OpenAI SDK는 `2.54.0`이다. Task 7에서 로컬 입력 추정용 `tiktoken`만 새로 추가·잠금하고 프레임워크·SDK 업그레이드는 하지 않는다.

**Spec:** [v2 설계서](../specs/2026-10-31-agent-v2-design.md), [계획·실행·저장 상세 계약](../specs/2026-11-01-agent-v2-contracts.md). 두 문서를 함께 읽는다.

**현재 상태:** 구현 계획 작성만 수행했다. 아래 체크박스·커밋·테스트·DB 변경·모델 평가는 모두 향후 실행 항목이며 지금 실행한 결과가 아니다. 제품 구현은 별도 요청 뒤에 시작한다.

## Global Constraints

- 기본은 v1, 새 대화의 첫 요청 전에 v1·v2 선택, 첫 요청 수락 뒤 버전 고정. 기존 대화·결과·v1 체크포인트는 자동 이관하지 않는다.
- v2 실행 도구는 `forward_lookup`, `reverse_search`, `compare_runs` 세 가지다. `generate_answer`를 중간 도구로 노출하지 않고 일반 설명·해석은 답변 작성 노드로 통합한다.
- 계획 제출은 native `submit_plan` 단일 호출. 최초 Decisions 검증은 없다. 실제 도구는 코드가 순차 실행한다.
- 원문 수치·단위·조건·정렬·후보 개수 정책을 보존한다. 모델이 단위 배율을 바꾸거나 원문에 없는 조건 완화·후보 제한을 추가하지 않는다.
- 결과 참조는 생산 단계·등록 필드·범위를 명시한다. 모델이 실제 JSON 경로·임의 실행 코드·실제 Run ID/버전을 만들지 않는다.
- 검색 후보와 확인된 비교 대상을 구분한다. 첫 두 후보 자동 선택·임의 기준/축 지정은 금지한다. 기준 없이 가능한 값·절대 차이·범위 비교는 유지한다.
- 내부 연산은 최솟값·최댓값·차이·배수·비율·평균. 누락을 0으로 만들거나 필요한 집합에서 몰래 제외하지 않는다.
- 같은 도구 자동 재시도 없음. 최초 계획 외 **요청 전체 재계획 최대 2회**, 근거가 충분한 **답변 수정 별도 최대 1회**. 대기·재개·재시작으로 한도를 초기화하지 않는다.
- 실험 수치 표·관찰 문장은 코드로 렌더링한다. LLM의 실험 답변 자유 해석·가정·한계에는 실험 수치·백분율·배율·공정 조건 숫자 재서술을 금지하는 v1 정책을 유지한다.
- 실제 Run 요청·혼합 답변은 마지막에 Decisions 한 요청으로 질문 요구·근거 일치·해석 범위를 각각 판정한다. `choice`로 분기하며 `probabilities`·`confidence`는 기록만 한다.
- 의미 검증 미통과가 남아도 마지막 코드 검사 통과 답변을 표시한다. 검토 상태는 상세정보에만 표시하고 답변 옆 배지는 붙이지 않는다. 유효한 초안 자체가 없으면 코드가 확인한 결과·오류를 안내한다.
- 순수 일반 지식은 Decisions 생략. 정상 호출 수는 일반 LLM 2회, 실험 답변은 일반 LLM 2회 + Decisions 1회다.
- 최종 답변 우선, 주요 중간 검색·비교 결과는 접어서 제공하며 결과별 Run을 판단 기록 대상으로 선택할 수 있게 한다. 불변 `executionId`·`stepId`·`groupId`·Run 버전을 보존한다.
- 계획·재계획 기본값은 `gpt-6-luna`의 `low`이고, 답변 작성은 v1 설정을 상속한다. Decisions 기본 모델 제안은 `gpt-6-luna`. 실제 `.env`·비밀값은 문서·fixture·로그에 넣지 않는다.
- 상세 계약 §10의 초기 예산을 이 계획의 설정 기본값으로 채택한다: 수정본당 **16단계**, 요청당 **12회 도구 실행**, 생성 출력 **6,000토큰**, 역할별 입력 기본 **24,000토큰** 이하와 실제 모델 문맥 제한, 호출 **30초**, 사용자 확인 대기 제외 자동 처리 **600초**, lease **60초**, 호출 deadline + **10초** 여유, 부분 종료 작성 **1회**, 전체 모델 요청 **13회 이내**, 숨겨진 SDK 재시도 **0**. 최적값 주장이 아니라 평가로 조정할 초기값이다.
- 신규 답변 계열은 `(implementationId=v2, graphVersion=v2, schemaVersion=1)`이다. 기존 v1 답변 schemaVersion 2·3과 혼동하거나 숫자 하나로 판별하지 않는다.
- 실제 실험 payload·대화·판정 로그·DB·스크린샷은 Git에 넣지 않는다. 테스트는 소량의 인공 데이터, 실데이터 평가는 저장소 밖 경로를 사용한다.
- 구현은 `main`에서 분기한 `feat/agent-graph-v2` 등 별도 브랜치에서 진행한다. 현재 문서 worktree의 미커밋 문서를 유실시키지 않는다. PR·팀원 승인·필수 검증 뒤 병합하며 현재 단계에서는 commit/push/PR도 실행하지 않는다.

## Review Focus

1. 실행 예약 직후 또는 API 응답 수신 뒤 저장 전 worker가 죽음: 저장 상태 대조 후 동일 도구를 재실행하지 않고 카운터를 보존한다 — Task 3·9.
2. Run이 첨부된 개념 질문과 실제 Run 비교를 일반 지식으로 오분류함: 첨부만으로 강제 조회하지 않되 실제 실험 요청을 검토 생략으로 우회하지 않는다 — Task 4·9.
3. 같은 Run이 중간 검색과 최종 검색에 동시에 등장함: 기록·후속 참조가 선택한 execution/group을 그대로 가리킨다 — Task 3·11.
4. 도구 호출 성공·검증 통과지만 다음 입력 필드가 누락됨: 0건·영구 누락·통신 실패를 구분하고 다음 실행을 막는다 — Task 4·7.
5. 전송 수락 여부 미확정 또는 오래된 resume 중 버전 선택: 원래 본문·idempotency key·대화 버전을 보존하고 오래된 worker/응답을 거부한다 — Task 2·9·10.

---

## 작업 구조와 공통 인터페이스

경로는 저장소 루트 기준이다. 한 사용자 기능의 생산자·소비자가 연결되어 있으므로 별도 독립 프로젝트로 분리하지 않고 계약 순서의 단일 계획으로 진행한다. 각 task는 독립 검증·리뷰·커밋 단위다.

| 영역 | 파일과 책임 |
|---|---|
| 공통 계약 | `docs/contracts/agent-v2.*.json`, `agent/src/contracts/v2.ts`, `agent/python/src/kplasma_agent/v2/contracts.py`, `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2Contracts.java` |
| 서버 버전·실행 기록 | 기존 `AgentRequestService`/`Repository`, 신규 `agent/v2` 서비스·저장소, 신규 Flyway migration. v1의 단일 operation/result를 반복 덮어쓰지 않는다. |
| Python v2 핵심 | 신규 `v2/plan_validation.py`, `bindings.py`, `derivations.py`, `model_gateway.py`, `decisions_client.py`, `executor.py`, `budget.py`, `composition.py`, `review.py`, `state.py` |
| 그래프·worker | 신규 `graphs/v2.py`, `graphs/registry.py`, 기존 `worker.py`와 `backend_client.py`. v1 그래프 알고리즘은 유지한다. |
| 화면·기록 | 기존 API·대화 훅·AnswerView·기록 화면, 신규 `V2AnswerView`, `V2StepResults`, `V2AnswerDetails`. Run 상세 모달과 답변 메타데이터 상세를 혼동하지 않는다. |
| 검증·평가 | 공유 인공 JSON fixture, Python/Java/TS 테스트, 모의 v2 실행 harness·Playwright, 별도 opt-in live eval runner |

Task 1이 생산할 이름을 후속 task에서 그대로 사용한다. 내부 Python 계획은 snake_case, 기존 HTTP/스냅샷 계열은 camelCase다. 필드 변환은 각 경계의 직렬화 함수 한 곳에서 수행한다.

- `GraphVersion`, `PlanDraft`, `ValidatedPlan`, `AcceptedPlan`, `StepSpec`, `BindingContext`, `ResolvedInputs`, `InputBlocked`, `Quantity`, `StepResult`, `StepExecution`, `PendingV2Input`, `EvidenceRegistry`.
- `PlanningContext`, `AnswerContext`, `ReviewContext`, `ModelPermit`, `ModelOutcome`, `ModelUsage`, `PlanCall`, `DataAnswerDraft`, `GeneralAnswerDraft`, `RenderedAnswer`, `ReviewDecision`, `BudgetState`, `GraphV2AnswerSnapshotV1`.
- `ValidatedPlan`은 코드 검사 결과이고 `AcceptedPlan`의 revision·execution/근거 ID는 서버가 발급한다. 모델의 성공 선언을 이 타입으로 신뢰하지 않는다.

서버는 요청 수락 시 실행 예산을 snapshot으로 고정해 claim/조회에 제공한다. Python 설정은 서버 상한을 완화하지 않고 더 엄격하게만 적용할 수 있다. `inputRevision`은 승인된 입력이 바뀔 때 증가하고 계획 revision과 별개다. 모델 예약 키는 역할·계획/입력 수정본·초안 ID에 연결하며, 답변 수정/부분 종료의 별도 카운터는 요청 전체에서 유지한다. 과거 입력의 초안을 현재 입력의 마지막 유효 답변으로 재사용하지 않는다.

## Task 1: v2 계약과 공유 인공 fixture 고정

**Files:**
- Create: `docs/contracts/agent-v2.openapi.json`, `docs/contracts/agent-v2.plan.schema.json`, `docs/contracts/agent-v2.answer.schema.json`
- Create: `agent/src/contracts/v2.ts`, `agent/tests/v2-contracts.test.ts`, `agent/tests/support/v2/contracts.json`
- Create: `agent/python/src/kplasma_agent/v2/__init__.py`, `agent/python/src/kplasma_agent/v2/contracts.py`, `agent/python/tests/v2/__init__.py`, `agent/python/tests/v2/conftest.py`, `agent/python/tests/v2/test_contracts.py`
- Create: `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2Contracts.java`, `backend/src/test/java/com/kplasma/analysisagent/agent/v2/V2ContractTest.java`
- Modify: `agent/src/contracts/index.ts`, `agent/src/index.ts`
- Modify: `backend/build.gradle`의 test resources에 공유 인공 fixture 경로를 등록한다. fixture 사본을 세 언어에 따로 만들지 않는다.
**Interfaces:**
- Consumes: 두 spec의 필드·상태·선택지·버전 축.
- Produces: 위 공통 타입, TS `isGraphV2AnswerSnapshot(value: unknown): value is GraphV2AnswerSnapshotV1`, Python `v2_fixture(name: str) -> dict` 테스트 fixture. JSON fixture 이름은 `nested_plan`, `data_answer`, `general_answer`, `partial_compare`, `pending_selection`, `review_issue`로 고정한다.

- [ ] **Step 1: 계약 실패 테스트 작성.** Python `test_v2_discriminator_does_not_change_v1`, TS `rejects_v1_schema_3_as_graph_v2`, Java `rejectsUnknownGraphVersion`을 추가한다. 핵심 단언:
  ```python
  answer = GraphV2AnswerSnapshotV1.model_validate(v2_fixture("data_answer"))
  assert (answer.implementation_id, answer.graph_version, answer.schema_version) == ("v2", "v2", 1)
  ```
  v1 fixture를 v2로 파싱하면 실패하고, 과거 v1 guard·직렬화는 그대로여야 한다. 실제 Run을 포함하지 않는 동일 fixture를 세 언어가 읽는다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_contracts.py -q`; `npm exec -w agent -- vitest run tests/v2-contracts.test.ts`. 새 타입/구현 부재로 실패해야 하며 0 tests 성공은 인정하지 않는다.
- [ ] **Step 3: 계약 구현.** 계획의 최상위 5필드·종류별 닫힌 단계 스키마·등록 참조·출력 요구·`await_input`·답변/실행/검토의 독립 상태를 정의한다. fixture에 Run 버전과 불변 execution 출처를 포함한다. 기존 `ToolName`·v1 모델을 세 도구로 축소하지 않는다.
- [ ] **Step 4: GREEN 확인.** 위 두 명령과 `backend/gradlew -p backend test --tests '*V2ContractTest' --console=plain`을 실행한다. 세 소비자 파싱과 기존 `agent/tests/contracts.test.ts`, Python wire 회귀가 통과해야 한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_contracts.py agent/python/tests/test_contracts.py agent/python/tests/test_answer_v2_wire.py -q
  npm exec -w agent -- vitest run tests/v2-contracts.test.ts tests/contracts.test.ts
  backend/gradlew -p backend test --tests '*V2ContractTest' --console=plain
  ```

- [ ] **Step 5: Commit.** 이 task의 계약·fixture·테스트만 stage하고 `feat: define graph v2 contracts`로 커밋한다.

## Task 2: 대화 버전 고정과 worker 배분

**Files:**
- Create: `backend/src/main/resources/db/migration/V8__agent_graph_versions.sql`, `backend/src/main/java/com/kplasma/analysisagent/agent/v2/GraphVersionPolicy.java`
- Create: `backend/src/test/java/com/kplasma/analysisagent/workspace/AgentGraphVersionTest.java`
- Modify: `backend/src/main/java/com/kplasma/analysisagent/agent/AgentRequestService.java`, `backend/src/main/java/com/kplasma/analysisagent/agent/AgentRequestRepository.java`, `backend/src/main/java/com/kplasma/analysisagent/agent/AgentWorkerController.java`
- Modify: `backend/src/main/java/com/kplasma/analysisagent/contract/WorkspaceDto.java`, `backend/src/main/java/com/kplasma/analysisagent/workspace/WorkspaceService.java`, `agent/src/contracts/index.ts`
**Interfaces:**
- Consumes: `GraphVersion`, 기존 StateToken·idempotency·claim fencing.
- Produces: `Submission.graphVersion?`, request view/row `graphVersion`, 대화 `agentGraphVersion`, claim `supportedGraphVersions?`; `GraphVersionPolicy.resolve(pinned, submitted) -> GraphVersion`.

- [ ] **Step 1: 버전·전송 불확실성 테스트 작성.** `pins_graph_on_first_accepted_request`, `old_worker_claims_only_v1`, `rejects_mismatching_version`, `same_idempotency_key_replays_original_version`을 추가한다. 생략한 첫 요청은 v1, v2 수락 뒤 생략은 v2, 변경 시 409 `GRAPH_VERSION_MISMATCH`, v1-only claim은 v2 job을 가져가지 않아야 한다.
- [ ] **Step 2: RED 확인.** `backend/gradlew -p backend test --tests '*AgentGraphVersionTest' --console=plain`. 현재 graphVersion 부재 때문에 실패해야 한다. Docker/Testcontainers PostgreSQL이 필요하다.
- [ ] **Step 3: 버전 정책 구현.** 첫 수락 트랜잭션에서 대화·요청·문맥 버전을 함께 고정한다. 과거 요청/비어 있지 않은 대화는 v1, pristine 대화만 미고정으로 처리한다. `conversation.version`은 그래프 버전으로 재사용하지 않는다. claim 미지정은 v1만 허용하고 v2 미지원/불일치는 조용한 fallback 없이 오류로 반환한다. V8이 실행 시 이미 쓰였으면 다음 migration 번호를 사용하며 적용된 migration은 수정하지 않는다.
- [ ] **Step 4: GREEN·회귀 확인.** 위 명령과 기존 `AgentRequestPersistenceTest`, `WorkspacePersistenceTest`를 실행한다. 새 대화·초기화의 기존 삭제 범위와 epoch fencing을 유지한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  backend/gradlew -p backend test --tests '*AgentGraphVersionTest' --tests '*AgentRequestPersistenceTest' --tests '*WorkspacePersistenceTest' --console=plain
  ```

- [ ] **Step 5: Commit.** 명시한 파일만 stage하고 `feat: pin agent graph versions per conversation`으로 커밋한다.

## Task 3: 단계별 실행·계획·모델 예약 저장과 API

**Files:**
- Create: `backend/src/main/resources/db/migration/V9__agent_v2_executions.sql`
- Create: `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2ExecutionRepository.java`, `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2ExecutionService.java`, `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2WorkerController.java`
- Create: `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2AnswerValidator.java`
- Create: `backend/src/test/java/com/kplasma/analysisagent/agent/v2/V2ExecutionPersistenceTest.java`
- Create: `agent/python/src/kplasma_agent/v2/backend.py`, `agent/python/tests/v2/test_backend.py`
- Modify: `backend/src/main/java/com/kplasma/analysisagent/agent/AgentRequestService.java`, `backend/src/main/java/com/kplasma/analysisagent/workspace/SnapshotValidator.java`, `agent/python/src/kplasma_agent/backend_client.py`
**Interfaces:**
- Consumes: Task 1 DTO, Task 2 graphVersion와 기존 claimGeneration/requestRevision/epoch.
- Produces: Python `V2ExecutionPort.accept_plan(ValidatedPlan) -> AcceptedPlan`, `start_step(AcceptedPlan, StepSpec, ResolvedInputs) -> StepExecution`, `load_context(execution_id) -> BindingContext`, `save_result(execution_id, StepResult) -> StepExecution`, `get_execution(execution_id) -> StepExecution`, `reserve_model(kind, key) -> ModelPermit`, `complete_model(attempt_id, ModelOutcome) -> None`, `get_model_attempt(attempt_id) -> ModelOutcome | None`, `needs_input(PendingV2Input)`, `finalize(GraphV2AnswerSnapshotV1)`.

- [ ] **Step 1: 저장·충돌·유실 테스트 작성.** `does_not_overwrite_first_search`, `rejects_late_result_after_cancel_or_new_epoch`, `same_execution_reservation_is_idempotent`, `same_run_in_two_executions_keeps_both_origins`를 추가한다. 첫 검색·비교·재검색의 결과가 세 execution으로 남고 lease/revision 불일치 결과는 현재 상태에 적용되지 않아야 한다.
- [ ] **Step 2: RED 확인.** `backend/gradlew -p backend test --tests '*V2ExecutionPersistenceTest' --console=plain`; `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_backend.py -q`.
- [ ] **Step 3: 저장·API 구현.** 상세 계약 §9.3의 steps/context/outputs/result와 조회를 실행 단위로 분리한다. `POST /internal/agent/requests/{id}/plans`, `POST .../{id}/model-attempts`, `POST .../{id}/model-attempts/{attemptId}/complete`와 예약/결과 조회를 기존 내부 인증·fencing 아래 제공한다. permit에 역할·고정 입력 수정본·deadline을 포함한다. 모델 결과는 공개 응답 값·상태·usage를 저장하고 키나 비공개 추론 텍스트를 복사하지 않는다. 입력·Run 버전·후보 그룹·필요 근거는 서버가 확인하고 단일 root operation/result를 반복 덮어쓰지 않는다. 기존 Java 조회/Python 계산/코드 검증 책임을 이동하지 않는다. 모델/도구 카운터는 I/O 전에 원자적으로 예약하며 유실 뒤 조회는 재실행이 아니다.
  - v2 tool 이름은 child 실행에 기록한다. legacy root `operationKind`에 `composite`를 넣어 기존 heartbeat allowlist를 느슨하게 바꾸지 않는다. 새 단계 응답의 requestRevision/claimGeneration을 adapter에 반영하고 모든 완료 저장을 같은 fencing으로 검사한다.
  - `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2AnswerValidator.java`도 이 task에서 만들어 v2 finalize를 등록한다. 저장된 child 실행·근거에 대조해 새 스냅샷 계열과 `COMPOSITE_ANSWER`/`GENERAL_ANSWER`를 검사한다. 원래 v1 finalize 검증을 전체적으로 느슨하게 바꾸지 않는다.
- [ ] **Step 4: GREEN 확인.** 위 명령과 `AgentRequestPersistenceTest`를 실행한다. lease를 잃거나 새 대화로 넘어간 요청의 지연 응답이 결과·기록을 되살리지 않아야 한다. 미저장 orphan 실행은 불확실한 실패로 남기고 자동 재호출하지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  backend/gradlew -p backend test --tests '*V2ExecutionPersistenceTest' --tests '*AgentRequestPersistenceTest' --console=plain
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_backend.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: persist scoped v2 executions and call reservations`로 커밋한다.

## Task 4: 도구 등록부·계획 검사·타입 있는 참조 해석

**Files:**
- Create: `agent/python/src/kplasma_agent/v2/tool_registry.py`, `agent/python/src/kplasma_agent/v2/plan_validation.py`, `agent/python/src/kplasma_agent/v2/bindings.py`
- Create: `agent/python/tests/v2/test_plan_validation.py`, `agent/python/tests/v2/test_bindings.py`
- Modify: `agent/python/src/kplasma_agent/v2/contracts.py`, `docs/contracts/agent-v2.plan.schema.json`
**Interfaces:**
- Consumes: `PlanDraft`, `BindingContext`, 기존 `ForwardInputs`/`ReverseInputs`/`CompareToolInputs`와 지표·비교 필드 등록부.
- Produces: `submit_plan_tool_schema() -> dict`, `validate_plan(plan: PlanDraft, context: BindingContext) -> ValidatedPlan`, `resolve_step_inputs(step: StepSpec, context: BindingContext) -> ResolvedInputs | InputBlocked`, `check_outputs(step: StepSpec, result: StepResult) -> InputBlocked | None`.

- [ ] **Step 1: 검사·바인딩 테스트 작성.** `rejects_cycles_unknown_fields_and_forged_versions`, `rejects_json_path_and_unconfirmed_candidates`, `catches_producer_field_omission_before_execution`, `partial_verified_result_still_blocks_next_input`, `run_request_cannot_use_general_only_bypass`를 추가한다. `InputBlocked.missing_fields == ['iedWidth']`와 다음 도구 호출 0회를 단언한다. Run 첨부만 된 ‘IED가 뭐야?’는 일반 지식 분류를 허용한다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_plan_validation.py agent/python/tests/v2/test_bindings.py -q`.
- [ ] **Step 3: 검사·참조 구현.** 세 사용자 확정 도구 설명을 v2 등록부에 원문대로 넣는다. 구조·의존·등록 필드/단위/개수·확인된 범위를 검사하고 값이 바인딩된 뒤 기존 도구 모델을 재검사한다. `run_if`는 명시된 결과 상태/개수 조건만, `requires` 미충족은 중단으로 처리한다. 원문 이해를 코드가 완전히 증명한다고 가정하지 않는다.
- [ ] **Step 4: GREEN·단위 회귀 확인.** 위 명령과 기존 `test_default_units.py`, `test_search_units.py`, `test_comparison_fields.py`를 실행한다. 생략 단위 null·기존 정렬/범위·baseline 없이 가능한 비교를 바꾸지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_plan_validation.py agent/python/tests/v2/test_bindings.py agent/python/tests/test_default_units.py agent/python/tests/test_search_units.py agent/python/tests/test_comparison_fields.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: validate v2 plans and resolve typed references`로 커밋한다.

## Task 5: 코드 내부 연산과 파생 근거

**Files:**
- Create: `agent/python/src/kplasma_agent/v2/derivations.py`, `agent/python/tests/v2/test_derivations.py`
- Modify: `agent/python/src/kplasma_agent/v2/contracts.py`, `agent/tests/support/v2/contracts.json`
**Interfaces:**
- Consumes: `Quantity`, 등록 지표/단위, 타입 있는 피연산자와 불변 출처.
- Produces: `compute_derived(operation: str, operands: list[Quantity], options: dict) -> StepResult`. `options`는 연산별 닫힌 모델로 검증하며 임의 식을 받지 않는다.

- [ ] **Step 1: 연산 실패 테스트 작성.** `max_for_both_flux_and_min_for_both_width`, `missing_member_blocks_aggregate`, `ratio_zero_denominator_is_unavailable`, `signed_difference_requires_direction`, `does_not_reuse_rounded_display_value`를 추가한다. 인공 eV 값 8·6의 최솟값은 6, 8·null은 8이 아닌 계산 불가, 분모 0은 실패 상태여야 한다. 원본 6.04를 표시 6.0으로 바꾸어 임계값에 쓰지 않는다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_derivations.py -q`.
- [ ] **Step 3: 여섯 연산 구현.** 단위 변환·유한수 정책은 기존 코드 기준으로 재사용한다. 산술평균과 가중평균을 바꾸지 않고, 기준 없는 절대 차이와 명시된 방향의 차이를 구분한다. 결과에 연산·피연산자·단위·Run 버전·출처 execution을 연결한다. 미등록 연산·단위 조합을 계산 코드 생성으로 해결하지 않는다.
  - 연산 이름은 `min`, `max`, `difference`, `scale`, `ratio`, `mean`. `Quantity`는 physical 값과 dimensionless 값을 구분하며 factor/비율의 내부 단위는 `1`로 한다. 측정값의 unit=null을 무차원으로 간주하지 않는다. scale은 물리값·무차원 factor, ratio는 명시된 분자·분모, difference는 `mode=absolute|signed`와 승인된 피연산자 방향을 사용한다.
- [ ] **Step 4: GREEN 확인.** 위 명령과 기존 `test_units.py`, `test_numeric_properties.py`, `test_compare.py`를 실행해 기존 수치 정책을 보존한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_derivations.py agent/python/tests/test_units.py agent/python/tests/test_numeric_properties.py agent/python/tests/test_compare.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: derive grounded numeric conditions in code`로 커밋한다.

## Task 6: 역할별 모델 설정과 계획·답변·Decisions 어댑터

**Files:**
- Create: `agent/python/src/kplasma_agent/v2/settings.py`, `agent/python/src/kplasma_agent/v2/model_gateway.py`, `agent/python/src/kplasma_agent/v2/decisions_client.py`
- Create: `agent/python/tests/v2/test_model_gateway.py`, `agent/python/tests/v2/test_decisions_client.py`, `agent/python/tests/v2/test_settings.py`
- Modify: 필요 시 기존 `agent/python/src/kplasma_agent/model_client.py`의 공용 schema 변환 유틸리티만 재사용/추출한다. v1 호출 정책은 바꾸지 않는다.
**Interfaces:**
- Consumes: `Settings`, Task 1 context/draft/permit 타입, Task 3 `V2ExecutionPort`, Task 4 `submit_plan_tool_schema`.
- Produces: `V2Settings.from_env(base: Settings) -> V2Settings`; `V2ModelGateway(settings: V2Settings, journal: V2ExecutionPort, transports, input_guard: Callable[[dict, str], None])`의 `submit_plan(context: PlanningContext, permit: ModelPermit) -> PlanCall`, `compose(context: AnswerContext, permit: ModelPermit) -> DataAnswerDraft | GeneralAnswerDraft`, `review(context: ReviewContext, permit: ModelPermit) -> ReviewDecision`.

- [ ] **Step 1: 전송 계약 테스트 작성.** `native_submit_plan_is_the_only_function`, `replan_feedback_has_no_unmatched_native_call`, `defaults_v2_planner_to_gpt6_luna_low_and_inherits_answer_settings`, `explicit_v2_planner_overrides_apply_to_initial_and_replan`, `review_sends_three_named_choices_once`, `review_refusal_is_unavailable`, `does_not_retry_transport_failure`를 MockTransport/가짜 SDK로 고정한다. API 요청 수 1회, SDK `max_retries=0`, 일반 지식에서 review 호출 0회는 후속 그래프 테스트와 연결한다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_model_gateway.py agent/python/tests/v2/test_decisions_client.py agent/python/tests/v2/test_settings.py -q`.
- [ ] **Step 3: 어댑터 구현.** `AGENT_V2_PLAN_MODEL` 미지정은 `gpt-6-luna`, `AGENT_V2_PLAN_REASONING_EFFORT` 미지정은 `low`로 한다. 초기 계획과 재계획 모두 이 설정을 쓴다. `AGENT_V2_ANSWER_MODEL`과 `AGENT_V2_ANSWER_REASONING_EFFORT` 미지정은 각각 base.model과 base.reasoning_effort를 상속한다. `AGENT_V2_DECISIONS_MODEL` 기본은 `gpt-6-luna`. v1 환경 값을 강제로 덮어쓰지 않는다. 생성은 기존 Responses SDK로, Decisions는 기존 의존성 `httpx`의 `POST /v1/decisions` 어댑터로 구현해 잠금 SDK 업그레이드에 의존하지 않는다. endpoint는 `AGENT_V2_DECISIONS_BASE_URL`, 기존 OpenAI base URL, 공식 기본 URL 순으로 해석하고 숨겨진 다른 제공자로 fallback하지 않는다. base URL의 `/v1` 중복 여부를 정규화하고 테스트한다.
  - compose의 응답 스키마는 context 모드에 맞는 `DataAnswerDraft` 또는 `GeneralAnswerDraft` 하나로 선택한다. 두 형태를 모델이 임의 선택하게 두지 않는다. gateway는 주입받은 `input_guard(payload, role)`를 전송 전에 호출한다. Task 7이 실제 guard를 제공하고 이 task의 단위 테스트는 가짜 guard를 쓴다.
  - 생성 역할의 문맥 상한은 `AGENT_V2_PLAN_CONTEXT_TOKENS`·`AGENT_V2_ANSWER_CONTEXT_TOKENS`로 명시할 수 있다. 미지정 시 알려진 모델 메타데이터를 사용한다. 2026-11-01 공식 문서 기준 [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)·[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)는 각각 1,050,000 문맥이다. 미등록 모델은 이름을 바꾸지 않고 실제 상한 설정을 요구한다. 이 큰 모델 상한과 별개로 24,000 입력·6,000 출력의 초기 애플리케이션 예산을 적용한다.
  - gateway는 위 생성자 의존성을 주입받고 유효한 `ModelPermit` 없이 API를 호출하지 않는다. 응답/usage 또는 호출 오류를 `complete_model`로 저장한 뒤 반환한다. 완료된 permit 재사용은 기록된 값을 읽고, 완료 여부 불명 예약으로 같은 API를 재전송하지 않는다. 이를 `reused_completed_permit_uses_recorded_output`으로 검사한다.
  - native 계획 성공 뒤 모델의 확인 문장을 받으려고 추가 호출하지 않는다. replan에는 이전 계획·오류를 데이터로 보내며 native call을 재사용하면 반드시 대응하는 call_id/output을 함께 유지한다.
  - Decisions는 `input_json`의 공유 근거와 `type=choice`, 고유 `name`, `{value, description}` 선택지의 세 질문을 사용한다. 공식 반환은 `answers[].choice`, `probabilities: [{value, probability}]`, `confidence`다. 정확한 형태는 [공식 가이드](https://developers.openai.com/api/docs/guides/decisions) 기준으로 fixture에 고정한다. scalar probability나 문자열 배열로 잘못 파싱하지 않는다.
  - 필수 질문/타입/선택지 누락·거절은 검토 미완료로 처리한다. 확률 크기와 confidence를 분기 임계값에 사용하지 않는다. 응답 원문과 사용량을 보존해도 키·Authorization은 로그에 남기지 않는다.
  - 통신 실패와 refusal·invalid output을 구분한다. 잘못된 schema/모델 설정의 HTTP 400은 코드 설정 오류로 종료하고 모델에게 고치라고 반복하지 않는다. 전송 결과가 불명인 usage는 0으로 꾸미지 않고 미확인으로 저장한다.
- [ ] **Step 4: GREEN·기존 모델 회귀 확인.** 위 명령과 기존 `test_model_client.py`, `test_tool_selection.py`를 실행한다. 실제 OpenAI 호출은 이 테스트에 포함하지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_model_gateway.py agent/python/tests/v2/test_decisions_client.py agent/python/tests/v2/test_settings.py agent/python/tests/test_model_client.py agent/python/tests/test_tool_selection.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: add bounded role-specific v2 model clients`로 커밋한다.

## Task 7: 순차 실행·중간 피드백·입력 확인·예산

**Files:**
- Create: `agent/python/src/kplasma_agent/v2/state.py`, `agent/python/src/kplasma_agent/v2/budget.py`, `agent/python/src/kplasma_agent/v2/executor.py`, `agent/python/src/kplasma_agent/v2/recovery.py`
- Create: `agent/python/tests/v2/fakes.py`, `agent/python/tests/v2/test_executor.py`, `agent/python/tests/v2/test_budget.py`, `agent/python/tests/v2/test_resume.py`
- Modify: `agent/python/src/kplasma_agent/v2/backend.py`
- Modify: `agent/python/pyproject.toml`, `agent/python/uv.lock` (로컬 preflight용 `tiktoken` 의존성·잠금만 추가)
**Interfaces:**
- Consumes: Task 3 `V2ExecutionPort`, Task 4 검사/참조 함수, Task 5 연산, Task 6 모델 gateway.
- Produces: `V2State`, `Feedback`, `BudgetExceeded`; `BudgetLedger(port: V2ExecutionPort, settings: V2Settings, clock)`의 `check_payload(payload: dict, role: str) -> None`, `reserve_model(kind: str, key: str) -> ModelPermit`, `reserve_tool(plan: AcceptedPlan, step: StepSpec, inputs: ResolvedInputs) -> StepExecution`. `SequentialExecutor(executions: V2ExecutionPort, budget: BudgetLedger, clock)`의 `execute_next(state: V2State) -> V2State`, `apply_input(state: V2State, pending_id: str, input: dict) -> V2State`; 순수 함수 `classify_feedback(state: V2State) -> Feedback`, `invalidate_dependents(old: AcceptedPlan, new: AcceptedPlan, executions: list[StepExecution]) -> set[str]`.
- `V2State`는 승인 입력 수정본·accepted plan·execution/근거·pending input·feedback·budget·현재 입력의 draft/review·terminal mode를 보유한다. `Feedback`는 reason_code·missing_fields·recoverability를, `BudgetState`는 replans_used·answer_rewrites_used·partial_finalizations_used·model_requests_used·tool_invocations_used·active_elapsed_seconds를 갖는다.

- [ ] **Step 1: 시나리오·한도 테스트 작성.** `verified_partial_is_not_ready`, `empty_search_is_not_transport_failure`, `missing_measurement_waits_without_relaxation`, `confirmed_input_binds_without_replan`, `replan_budget_is_shared_across_tools`, `independent_work_is_sequential`, `changed_dependency_invalidates_only_dependents`를 추가한다. 서로 다른 단계의 replan 두 번 뒤 세 번째 model permit은 거부되고, 정상 성공한 독립 작업은 재사용되어야 한다.
  ```python
  assert state.budget.replans_used == 2
  assert state.budget.answer_rewrites_used == 0
  assert state.feedback.missing_fields == ["iedWidth"]
  ```
  테스트 전용 `ScriptedGateway`, `FakeExecutionPort`, `ManualClock`를 `fakes.py`에서 정의하고 모델·DB 없이 상태 전이를 구동한다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_executor.py agent/python/tests/v2/test_budget.py agent/python/tests/v2/test_resume.py -q`.
- [ ] **Step 3: 실행기 구현.** ready 단계를 계획 순서로 하나씩 실행·검증한다. 필요 필드가 없으면 다음 도구를 호출하지 않는다. 실제로 가능한 등록 경로가 있을 때만 replan하고, 영구 누락은 `await_input` 확인 대기 또는 부분 종료로 처리한다. 조건/단위/선택/방향의 구조화된 확인만으로 채워지는 입력에는 replan 호출을 추가하지 않는다. 실험 누락값을 사용자 채팅 숫자로 대체하지 않는다.
  - replan·답변 수정·도구·총 모델·시간의 권한은 서버 예약 상태가 기준이다. 16/12/13/600 등 기본값을 `V2Settings`에서 관리하고 대기·재시작에 보존한다. 0건·필터 변경 없는 동일 실패를 횟수 소진용으로 반복하지 않는다.
  - `uv add --project agent/python tiktoken`으로 로컬 tokenizer만 추가하고 lockfile을 함께 갱신한다. 기존 프레임워크/SDK를 함께 업그레이드하지 않는다. 직렬화한 전체 텍스트 요청·도구 schema·질문을 `o200k_base`로 계산한 토큰 수에 10%와 1,024 여유를 둔 값을 초기 preflight 추정으로 사용한다. 사용자 문자열의 special-token 모양도 일반 텍스트로 인코딩한다. 이는 실제 모델 내부 포맷의 정확한 토큰 수가 아니다. [공식 문서](https://developers.openai.com/api/docs/guides/token-counting)에 따라 구조화 입력의 로컬 추정 한계를 명시하고 provider usage와 별도 기록·보정한다. 추가 token-count API 호출은 기본 경로에 넣지 않는다. 어림값을 실제 청구량으로 보고하지 않는다.
  - encoding cache는 실행 환경 준비 단계에서 구성하고 단위 테스트에는 가짜 counter를 주입해 숨겨진 네트워크 다운로드를 피한다. `input_budget_does_not_truncate_evidence_or_candidates`로 24,000/실제 문맥 한도 초과 시 범위 확인/오류와 원문·원본 결과 보존을 검사한다.
  - 모델 역할은 `PLAN_INITIAL`, `REPLAN`, `COMPOSE`, `ANSWER_REWRITE`, `PARTIAL_COMPOSE`, `REVIEW`로 예약한다. 같은 역할/입력/초안의 저장 결과는 복구할 수 있지만 승인 입력이 바뀐 경우 새 inputRevision을 사용한다. 재개로 replan/rewrite 전역 카운터를 초기화하지 않는다.
  - 새 전체 계획을 수락하고 입력·버전·출처 의미가 변한 단계와 의존 결과만 무효화한다. 동일 단계 ID라도 새 실행에는 새 execution ID를 쓴다. 예상하지 못한 guard/분기 결과를 임의 성공으로 바꾸지 않는다.
- [ ] **Step 4: GREEN 확인.** 위 명령과 Task 4·5 테스트를 실행한다. 가짜 clock으로 600초와 lease 여유를 검사하고 실제 sleep으로 한도를 시험하지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_executor.py agent/python/tests/v2/test_budget.py agent/python/tests/v2/test_resume.py agent/python/tests/v2/test_plan_validation.py agent/python/tests/v2/test_bindings.py agent/python/tests/v2/test_derivations.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: execute and replan v2 tasks with durable budgets`로 커밋한다.

## Task 8: 근거 답변 조립과 최종 판정 분기

**Files:**
- Create: `agent/python/src/kplasma_agent/v2/composition.py`, `agent/python/src/kplasma_agent/v2/review.py`
- Create: `agent/python/tests/v2/test_composition.py`, `agent/python/tests/v2/test_review_routing.py`
- Modify: `agent/python/src/kplasma_agent/explanations/answers.py`의 기존 수치 재서술 검사를 공용 함수로 추출하고 v1 동작은 유지한다.
**Interfaces:**
- Consumes: typed `EvidenceRegistry`, `DataAnswerDraft`/`GeneralAnswerDraft`, Task 7 `BudgetLedger`.
- Produces: `ReviewRoute` (`WAIT_INPUT`, `REPLAN`, `REWRITE`, `SHOW`, `SHOW_LAST`, `SHOW_RESULTS_ONLY`), `validate_no_run_numeric_restatement(texts: list[str]) -> None`, `assemble_answer(draft, evidence: EvidenceRegistry) -> RenderedAnswer`, `decide_review_route(state: V2State, review: ReviewDecision) -> ReviewRoute`, `build_snapshot(state: V2State) -> GraphV2AnswerSnapshotV1`.

- [ ] **Step 1: 답변·분기 테스트 작성.** `facts_render_from_code_not_llm_numbers`, `overclaim_uses_one_rewrite_not_tools`, `low_probability_issue_still_acts_on_choice`, `execution_missing_precedes_overclaim`, `review_unavailable_shows_last_code_valid_draft`, `partial_finalize_does_not_loop`를 추가한다. `overclaim` 확률 0.05여도 별도 threshold 없이 수정하며, 수정 뒤 또 overclaim이면 답변 표시·review ISSUE 기록으로 끝나야 한다. 코드 검사 실패 초안은 대신 표시하지 않는다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_composition.py agent/python/tests/v2/test_review_routing.py -q`.
- [ ] **Step 3: 조립·검토 분기 구현.** 코드 사실/관찰 텍스트와 근거 ID를 LLM의 정성적 해석과 조립한 뒤 그 전체를 Decisions에 보낸다. 데이터/입력 확인 → 보완 가능한 실행 누락 → 근거가 충분한 답변 오류 → 모두 정상 → 판단 불가 순으로 분기한다. protocol invalid는 미완료다. 한도 소진 뒤 부분 종료 모드는 한 번만 진입하고 그 검증 실패가 다시 일반 실행으로 돌아가지 않게 한다. 일반 지식의 생략은 PASS가 아닌 SKIPPED로 기록한다.
  - 마지막 유효 초안은 현재 승인 입력·대상 버전에 대해서도 유효해야 한다. 입력 확인으로 대상/조건이 달라진 뒤 과거 초안을 재사용하지 않으며 `old_input_draft_is_not_current_fallback`으로 고정한다. 유효 초안이 없으면 코드 결과·이유를 표시한다.
- [ ] **Step 4: GREEN·수치 회귀 확인.** 위 명령과 기존 `test_comparison_answer.py`, `test_answer_v2_wire.py`, `test_explanations.py`를 실행한다. Run 수치·RF 위상·공정 조건 숫자 재서술 금지와 지원하지 않는 특징값의 상태를 유지한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_composition.py agent/python/tests/v2/test_review_routing.py agent/python/tests/test_comparison_answer.py agent/python/tests/test_answer_v2_wire.py agent/python/tests/test_explanations.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: compose grounded v2 answers and bounded review routes`로 커밋한다.

## Task 9: LangGraph·worker·복구의 실제 연결

**Files:**
- Create: `agent/python/src/kplasma_agent/graphs/v2.py`, `agent/python/src/kplasma_agent/graphs/registry.py`
- Create: `agent/python/tests/v2/test_graph.py`, `agent/python/tests/v2/test_worker_recovery.py`
- Modify: `agent/python/src/kplasma_agent/worker.py`, `agent/python/src/kplasma_agent/backend_client.py`, 필요 시 `agent/python/src/kplasma_agent/tracing.py`
**Interfaces:**
- Consumes: Task 6~8의 models/executor/composition 및 기존 `ModelClient`, `RequestBackend`, `Settings`, checkpointer.
- Produces: `graphs/v2.py`의 `V2Dependencies(settings, models, executions, budget, clock)`와 `build_v2_graph(dependencies: V2Dependencies, checkpointer) -> CompiledStateGraph`; registry의 `GraphDependencies(legacy_model: ModelClient, backend: RequestBackend, settings: Settings, saver, v2_dependencies: V2Dependencies | None)`와 `build_graph_for_version(version: GraphVersion, dependencies: GraphDependencies) -> CompiledStateGraph`.

- [ ] **Step 1: 전체 그래프·복구 테스트 작성.** `normal_data_path_has_two_generation_calls_one_review`, `general_path_has_two_generation_calls_zero_review`, `v1_dispatch_is_unchanged`, `crash_after_reserve_does_not_reissue_tool`, `crash_after_response_does_not_reset_budget`, `stale_resume_cannot_switch_graph`를 추가한다. SDK 응답 유실·server 저장 완료/미완료 양쪽을 가짜 포트로 재현한다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/tests/v2/test_graph.py agent/python/tests/v2/test_worker_recovery.py -q`.
- [ ] **Step 3: 그래프 연결.** 설계서의 code/LLM/Decisions 노드를 연결하고 v1 경로는 기존 `build_graph`에 그대로 위임한다. claim의 고정 버전으로 factory를 고르고 v2 의존성은 필요한 요청에서 생성한다. 빈 plan·부분 결과·NEEDS_INPUT·실행 오류의 저장과 재개를 전용 v2 namespace에 묶는다. lease 갱신·취소·deadline은 각 I/O 전에 검사하고 늦은 응답은 fencing으로 막는다.
  - 노드 ID는 `plan → validate_plan → execute_step → check_step → compose_answer → check_answer → review_answer → route_review → finalize`를 기본으로 한다. `check_step`은 다음 `execute_step`으로, 일반 지식의 `check_answer`는 `finalize`로 분기한다. `guard_replan → replan → validate_plan`, `guard_rewrite → compose_answer`, `await_input → validate_plan`, `prepare_partial → compose_answer`, `select_final_output → finalize`의 예외 경로를 둔다. `plan`·`replan`·`compose_answer`만 일반 LLM, `review_answer`만 Decisions이고 나머지는 코드다. `compose_answer`의 mode로 최초/답변 수정/부분 종료를 구분하며 노드 방문 자체가 호출 예산을 새로 만들지 않는다.
  - `SequentialExecutor`는 위 의존성으로 factory 안에서 생성해 실행·입력 재개 노드에 주입한다. 외부 DAG의 각 step을 LangGraph 노드로 동적 생성하지 않고, 검증된 계획을 고정 실행 루프의 데이터로 처리한다.
  - 복구 시 checkpoint와 서버 execution/model 예약 상태를 대조한다. 완료된 결과만 복원하며 유실된 응답을 같은 호출 자동 반복으로 해결하지 않는다. 한도 밖 v1 retry/repair 루프나 v1 그래프 fallback을 v2에 적용하지 않는다.
- [ ] **Step 4: GREEN·기존 worker 회귀 확인.** 위 명령과 기존 `test_worker.py`, `test_checkpoint_adapter.py`, `test_graph_v1.py`, `test_tracing.py`를 실행한다. trace에는 버전·단계·실행·역할·추가 호출 이유·사용량을 연결하고 비밀값을 남기지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/tests/v2/test_graph.py agent/python/tests/v2/test_worker_recovery.py agent/python/tests/test_worker.py agent/python/tests/test_checkpoint_adapter.py agent/python/tests/test_graph_v1.py agent/python/tests/test_tracing.py -q
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: integrate durable graph v2 worker dispatch`로 커밋한다.

## Task 10: 새 대화 버전 선택과 v2 입력 확인 화면

**Files:**
- Create: `frontend/src/features/agent/GraphVersionSelector.tsx`, `frontend/src/features/agent/GraphVersionSelector.css`, `frontend/src/features/agent/V2PendingInputView.tsx`
- Create: `frontend/src/features/agent/v2-version-selection.test.tsx`, `frontend/src/features/agent/v2-pending-input.test.tsx`
- Modify: `frontend/src/features/agent/AgentPage.tsx`, `frontend/src/features/agent/useConversation.ts`, `frontend/src/features/agent/PendingRequest.tsx`, `frontend/src/api/agent.ts`, `frontend/src/api/workspace.ts`
**Interfaces:**
- Consumes: shared `GraphVersion`, version/pending API 계약, 기존 `RunSelectionPanel`과 상태 fencing.
- Produces: `GraphVersionSelector({value, locked, onChange})`; 대화 훅의 `selectedGraphVersion`, `versionLocked`, `selectGraphVersion(version)`; 기존 `submit`/`resume`에 고정 버전·구조화 입력 전달.

- [ ] **Step 1: 첫 화면·불확실 전송 테스트 작성.** `selects_v2_before_first_question_without_clearing_run_refs`, `defaults_new_chat_to_v1`, `locks_selector_during_send_uncertain`, `restores_pinned_version_after_refresh`, `resume_fills_only_requested_fields`를 추가한다.
  ```typescript
  expect(submittedBody.graphVersion).toBe('v2');
  expect(submittedBody.attachedRunRefs).toEqual(originalRefs);
  expect(screen.getByLabelText('Agent 버전')).toBeDisabled(); // SEND_UNCERTAIN
  ```
  selector가 현재 active request·과거 대화의 버전을 바꾸는 요청을 보내지 않는지 단언한다.
- [ ] **Step 2: RED 확인.** `npm exec -w frontend -- vitest run src/features/agent/v2-version-selection.test.tsx src/features/agent/v2-pending-input.test.tsx`.
- [ ] **Step 3: 선택·확인 UI 구현.** 첫 질문 전 빈 화면에서도 v1 기본·v2 시험 선택을 허용한다. 선택만 바꿀 때 workspace 새 대화/초기화 API를 호출하지 않는다. 첫 제출 본문과 idempotency key를 보존하고 수락 뒤에는 서버 버전을 따른다. 현재 대화의 버전은 읽기 전용이며 다른 버전은 새 대화에서 쓴다. v2 pending의 조건·단위·선택·기준/축·방향을 타입에 맞는 입력으로 받고 기존 v1 pending 화면은 유지한다.
- [ ] **Step 4: GREEN·기존 대화 회귀 확인.** 위 명령과 기존 `server-conversation.test.tsx`, `PendingRequest.test.tsx`, `conversation.test.tsx`를 실행한다. 늦은 응답이 새 대화의 선택·Run 참조를 덮어쓰지 않아야 한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  npm exec -w frontend -- vitest run src/features/agent/v2-version-selection.test.tsx src/features/agent/v2-pending-input.test.tsx src/features/agent/server-conversation.test.tsx src/features/agent/PendingRequest.test.tsx src/features/agent/conversation.test.tsx
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: select v2 for new conversations`로 커밋한다.

## Task 11: 복합 답변·접힌 중간 결과·상세 검토·판단 기록

**Files:**
- Create: `frontend/src/features/agent/V2AnswerView.tsx`, `frontend/src/features/agent/V2StepResults.tsx`, `frontend/src/features/agent/V2AnswerDetails.tsx`, `frontend/src/features/agent/v2-record-model.ts`, `frontend/src/features/agent/v2-answer.css`
- Create: `frontend/src/features/agent/v2-answer.test.tsx`, `frontend/src/features/agent/v2-record-source.test.tsx`
- Modify: `frontend/src/features/agent/AnswerView.tsx`, `frontend/src/features/agent/references.ts`, `frontend/src/features/archive/DecisionDialog.tsx`, `frontend/src/features/archive/ArchivePage.tsx`, `frontend/src/api/decisions.ts`
- Modify: `agent/src/contracts/answers.ts`, `agent/src/contracts/index.ts`, `backend/src/main/java/com/kplasma/analysisagent/agent/AgentRequestService.java`, `backend/src/main/java/com/kplasma/analysisagent/contract/WorkspaceDto.java`
- Modify: `backend/src/main/java/com/kplasma/analysisagent/decision/DecisionValidator.java`, `backend/src/main/java/com/kplasma/analysisagent/decision/DecisionService.java`, `backend/src/test/java/com/kplasma/analysisagent/decision/DecisionValidationTest.java`
**Interfaces:**
- Consumes: `GraphV2AnswerSnapshotV1`, 서버 execution·근거, 기존 결과 카드·기록 API.
- Produces: `V2AnswerView({turn, onAction})`, `V2AnswerDetails({snapshot})`, `buildV2RecordModel(turn, executionId, groupId, runRefs)`; 기존 `ReferenceOrigin`·기록 입력에 v2의 선택적 `executionId`, `stepId`를 추가하되 v2 결과에서는 필수 검증한다.

- [ ] **Step 1: 표시·출처 테스트 작성.** `shows_final_answer_before_collapsed_steps`, `review_issue_is_only_in_answer_details`, `general_review_is_skipped_not_passed`, `recording_same_run_preserves_selected_execution`, `forged_execution_origin_is_rejected`, `old_v1_archive_is_unchanged`를 추가한다. 같은 Run을 search_1과 search_2에 넣고 search_1에서 기록한 경우 execution_1·group_1·그 Run 버전이 저장되어야 한다.
- [ ] **Step 2: RED 확인.** `npm exec -w frontend -- vitest run src/features/agent/v2-answer.test.tsx src/features/agent/v2-record-source.test.tsx`; `backend/gradlew -p backend test --tests '*DecisionValidationTest' --console=plain`.
- [ ] **Step 3: 표시·기록 구현.** v2 discriminator를 먼저 검사한 뒤 v1/legacy renderer를 유지한다. 최종 답변 우선·주요 중간 결과 기본 접기·결과별 Run 선택을 제공하며 내부 프롬프트나 모든 계산 단계를 일반 화면에 출력하지 않는다. 무효화 결과는 현재 후보로 쓰지 않는다. **답변용 `V2AnswerDetails`**에 판정 상태와 세 항목 결과를 표시하고, Run용 `TurnDetailDialog`를 검토 상태 화면으로 바꾸지 않는다. 답변 옆 배지·확률 표시는 만들지 않는다.
  - server는 turn/execution/step/group/Run 버전의 실제 소속을 저장된 출처와 대조한다. 다른 단계의 같은 Run이라는 이유로 통과시키지 않는다. 기록 스냅샷은 고정하고 UI 접기 상태만 별도 변경한다. Task 3의 v2 완료 검증과 이 기록 검증은 각각 유지한다.
- [ ] **Step 4: GREEN·보관 회귀 확인.** 위 명령과 기존 `v1-answer.test.tsx`, `answer-rendering.test.tsx`, `chat-references.test.tsx`, `frontend/src/features/archive/decision.test.tsx`, backend `RunDeletionReferencesTest`를 실행한다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  npm exec -w frontend -- vitest run src/features/agent/v2-answer.test.tsx src/features/agent/v2-record-source.test.tsx src/features/agent/v1-answer.test.tsx src/features/agent/answer-rendering.test.tsx src/features/agent/chat-references.test.tsx src/features/archive/decision.test.tsx
  backend/gradlew -p backend test --tests '*DecisionValidationTest' --tests '*RunDeletionReferencesTest' --console=plain
  ```

- [ ] **Step 5: Commit.** task 파일만 stage하고 `feat: display and archive scoped v2 results`로 커밋한다.

## Task 12: 모의 전체 흐름·장애·화면 검증과 CI

**Files:**
- Create: `scripts/agent/verify-v2.mjs`, `agent/python/tests/v2/runtime_worker.py`
- Create: `frontend/src/features/agent/agent-v2.pw.ts`, `frontend/src/features/agent/agent-v2.playwright.config.ts`
- Modify: `scripts/agent/runtime.mjs`, `package.json`, `.github/workflows/ci.yml`
**Interfaces:**
- Consumes: 모든 v2 경로와 테스트 전용 `ScriptedGateway`. production에서 가짜 모델을 고르는 분기는 추가하지 않는다.
- Produces: `npm run test:e2e:v2`의 모의 통합 검증과 인공 데이터만 담는 외부 경로 산출물. `verify-v2.mjs`는 기본적으로 live API를 호출하지 않는다.

- [ ] **Step 1: 검증 시나리오를 먼저 작성.** 정상 nested flow, 원본 출력 누락 후 사용자 확인/재개, 계획이 `모두보다 높다`를 min으로 잘못 해석한 뒤 final review→max 재계획, 답변 과장 1회 수정 뒤에도 미통과한 답변 표시, 일반 지식 생략, 예약·저장 사이 restart, 두 검색의 같은 Run 기록, v1 회귀를 정의한다. 결과 membership·원래 조건·단위·출처·호출 수를 단언하고 특정 계획 JSON 문자열 하나만 정답으로 쓰지 않는다.
- [ ] **Step 2: RED 확인.** 신규 모의 시나리오를 현재 harness에 넣어 `node scripts/agent/verify-v2.mjs`를 실행한다. 실제 v2 경로 부재/누락을 검출해야 하며 임시 DB와 인공 fixture만 사용한다.
- [ ] **Step 3: harness 연결.** 기존 runtime 준비/정리를 재사용하되 v2 선택·가짜 모델 포트·server DB를 연결한다. 브라우저 네트워크 가로채기 화면 검증과 실제 Java/Python 모의 통합 결과를 구분해 기록한다. `package.json`에 `test:e2e:v2`를 추가하고 CI에서는 이 모의 경로만 실행한다. 임시 DB·artifact를 repo 밖 경로에 두고 실패 시에도 정리한다.
- [ ] **Step 4: GREEN·화면·전체 검증.** `npm run test:e2e:v2`; `npm exec -w frontend -- playwright test --config src/features/agent/agent-v2.playwright.config.ts`. 390 / 800 / 1008 / 1440px, ko-KR, Asia/Seoul, deviceScaleFactor 1로 새 버전 선택·입력·모달·접힌 결과·기록의 잘림/가로 넘침을 확인한다. 이어 아래 공통 검증 묶음을 한 번 실행한다. actual Run 이미지/로그는 CI artifact로 올리지 않는다.
- [ ] **Step 5: Commit.** task 파일만 stage하고 `test: cover v2 runtime recovery and user flows`로 커밋한다.

## Task 13: 평가 CLI·모델 비교·운영 문서

**Files:**
- Create: `agent/python/evals/v2_cases.py`, `agent/python/evals/v2_harness.py`, `agent/python/evals/run_v2.py`, `agent/python/evals/test_v2_harness.py`
- Create: `docs/development/agent-v2.md`
- Modify: `agent/python/evals/README.md`, `README.md`
**Interfaces:**
- Consumes: 최소 24개 인공 평가 사례와 같은 원문·데이터·설정의 v1/v2 결과.
- Produces: `evaluate_case(case, outcome) -> CaseScore`, `python -m evals.run_v2` CLI. 기본 `--dry-run`, 실제 모델은 명시적 `--live`와 `--output` 경로로만 호출한다. `--limit`, `--repeat`, `--graph-version`을 지원한다. v2 모델 비교는 Task 6의 계획 환경 변수 두 개로 실행을 구분하고 보고서에 적용값을 기록한다.

- [ ] **Step 1: 채점·보안 테스트 작성.** `dry_run_never_calls_model`, `accepts_equivalent_valid_plans`, `scores_shown_wrong_answer_even_if_review_passed`, `keeps_general_mixed_distinct`, `refuses_live_output_inside_repository`를 추가한다. 단순/복합/0건·누락·미지원/일반·혼합 사례를 모두 포함하고, 실제 모델 응답은 저장소 밖에 저장한다.
- [ ] **Step 2: RED 확인.** `uv run --project agent/python --frozen pytest agent/python/evals/test_v2_harness.py -q`.
- [ ] **Step 3: CLI·보고서 구현.** 코드 불변량·요구 충족·최종 제공 사실/해석 오류·대상/조건/단위·불필요한 수정·복구 성공·비용/지연을 분리한다. 상세 계약 §10의 네 가지 계획 설정을 같은 v2 평가 입력으로 비교하고 대표 실패 사례는 최소 3회 반복한다. 첫 계획의 의미 오류와 최종 답변 오류를 각각 집계한다. v1·v2 비교는 공통 모델 설정으로 별도 실행한다. Decisions 통과율로 정답률을 대신하지 않는다. 운영 문서에는 모델 상속/역할별 설정, 입력·출력·단계·호출/시간·lease 기본값, 평가 방법, 기존 대화 유지와 v2→v1 자동 fallback 없음, 진단 상태·수정 한도·수동 재질문 방법을 적는다.
- [ ] **Step 4: GREEN·실제 평가.** 먼저 위 pytest와 dry-run을 통과시킨다. 아래 CLI는 **`agent/python` 디렉터리에서** 실행한다.
  ```sh
  uv run --frozen python -m evals.run_v2 --dry-run --output /tmp/kplasma-v2-eval-dry
  uv run --frozen python -m evals.run_v2 --live --limit 1 --output /tmp/kplasma-v2-eval-smoke
  uv run --frozen python -m evals.run_v2 --live --limit 24 --repeat 1 --output /tmp/kplasma-v2-eval-live
  ```
  마지막 두 명령은 향후 구현 검수의 명시적 live 평가 단계이며 현재 실행하지 않는다. 실행 시 제공자 접근·모델 지원·예산을 확인하고 초기 smoke 뒤 전체 묶음으로 넓힌다. 실제 Run 데이터 평가를 추가하면 외부 입력 경로를 사용한다. 미실행이면 미실행으로 보고하고 품질 검증 완료로 처리하지 않는다.

  **GREEN 실행 명령(저장소 루트):**
  ```sh
  uv run --project agent/python --frozen pytest agent/python/evals/test_v2_harness.py -q
  ```

- [ ] **Step 5: Commit.** 코드·인공 사례·비밀값 없는 운영 문서만 stage하고 `test: add v2 evaluation and operations guide`로 커밋한다. live 출력은 stage하지 않는다.

## 실행 전 확인과 검증 명령

아래 명령은 향후 구현자가 실행한다. 현재 계획 작성에서는 실행하지 않았다.

- Node/npm·Java 21·uv·Python 지원 범위와 Docker/Testcontainers 가용성을 확인한다. 기존 lockfile을 먼저 사용한다.
- 실행 준비에서만 `npm ci`, `uv sync --project agent/python --frozen --extra tracing`를 수행한다. 현재 계획 문서 작성 단계에서는 설치하지 않는다.
- 구현 시점의 main에 별도 작업 브랜치를 만들고 승인된 두 spec와 이 계획을 함께 가져온다. 기존 문서 worktree와 다른 사람이 수정한 파일을 덮어쓰지 않는다.
- 위 V8/V9는 현재 스냅샷의 다음 번호다. 실행 시점의 main에 새 migration이 있으면 다음 미사용 번호로 조정하고 기존 migration은 변경하지 않는다.
- RED는 새 요구를 재현하는 테스트가 실제로 수집되어 실패하는지 확인한다. 환경 오류와 기능 실패를 구분한다. GREEN 확인 전 다음 task 완료나 성공을 기록하지 않는다.
- task별 커밋은 해당 Files와 직접 필요한 fixture·계약 변경만 포함한다. `git add .`·강제 reset·main 직접 push는 사용하지 않는다. 검증한 작업을 PR로 제출하고 팀원 승인 뒤 병합한다.

전체 검증은 루트에서 실행한다.

```sh
uv run --project agent/python --frozen --extra tracing pytest agent/python/tests agent/python/evals
uv run --project agent/python --frozen ruff check agent/python/src agent/python/tests agent/python/evals
uv run --project agent/python --frozen mypy agent/python/src
npm run verify:public-files
npm test
npm run typecheck
npm run lint
npm run build
backend/gradlew -p backend test --console=plain
npm run test:e2e
npm run test:agent:restart
npm run test:e2e:v2
```

원래 CI의 나머지 필수 검증도 유지한다. source/계약/검증 harness 변경 때문에 관련 reference·성능 검증이 영향받으면 해당 기존 명령을 추가한다. 실제 기준 데이터가 필요한 검증은 외부 데이터 공급 여부와 실행 여부를 별도로 남긴다. 한 번 통과한 검증은 새 변경·실패·미해결 우려가 있을 때만 다시 넓혀 실행한다.

## 의존 관계와 검수 산출물

`1 → 2 → 3`으로 서버 계약을 준비하고 `4·5·6`에서 검사/연산/모델 경계를 만든다. `7 → 8 → 9`에서 실행·답변·worker를 통합한다. `10 → 11`에서 화면과 기록을 연결하고 `12 → 13`에서 모의 전체 검증과 실제 평가를 완료한다. `4·5·6`은 설계상 경계가 있지만 실행 순서는 검토자가 선택한 방식에 따르며 지금 병렬 작업을 시작하지 않는다.

| 검수 산출물 | 소유 task |
|---|---|
| 세 언어 wire fixture·v1 호환·등록 도구/참조·실제 버전 검증 | 1~4 |
| 수치·연산·단위·0건/누락/오류·입력 확인·재개·전역 한도 | 4·5·7 |
| native 계획·역할 상속·한 번의 세 질문·확률 기록 전용·무재시도 | 6 |
| 코드 수치 렌더링·전체 본문 의미 검토·수정 1회·마지막 답변 표시 | 8 |
| 그래프 선택·checkpoint/fencing·중복/오래된 응답·재시작 | 2·3·9 |
| 첫 질문 전 버전 선택·잠금·접힌 중간 결과·출처별 기록·상세 검토 상태 | 10·11 |
| 네 폭의 화면·모의 전체 흐름·기존 필수 회귀·24개 이상 모델 평가 보고서 | 12·13 |

실제 코드·계약·UI 필수 검증 통과와 모델 평가 보고서가 opt-in v2의 검수 조건이다. 근거 없는 정확도 합격률을 만들지 않는다. 평가 결과와 남은 한계를 보고하되 기본값은 v1을 유지한다. v2 기본 전환은 이 계획의 작업이 아니다.

## 계획 자체 검토

- Spec coverage: 설계의 확정 항목과 상세 계약 §1~10을 위 task/검수 표에 연결했다.
- Step scan: 각 task는 테스트 추가 → RED → 명시 인터페이스 구현 → GREEN/관련 회귀 → 좁은 커밋으로 끝난다. 실제 구현 본문을 계획에 대신 작성하지 않았다.
- Type consistency: 공통 타입은 Task 1, backend port는 Task 3, 검사/연산/모델은 Task 4~6, 실행 상태/예산은 Task 7이 소유하며 뒤 task는 같은 이름을 소비한다.
- Review Focus: 다섯 위험 입력을 해당 task의 명시 테스트에 추가했다. 데이터 부족·의미 미통과·실행 실패를 서로 다른 상태로 다룬다.
- Proportion: 한 기능의 계약 경계별 13개 검수 단위로 제한했다. 이 문서는 실행 계획이며 제품 동작·모델 정확도를 검증한 결과가 아니다.

**현재 작업 결과:** 구현 계획 문서만 작성했다. 제품 코드·DB·의존성·테스트·실제 모델 평가·커밋·push·PR 실행은 하지 않았다. 구현 실행 방식은 아직 선택하지 않았으며 이후 구현 요청 시 정한다.

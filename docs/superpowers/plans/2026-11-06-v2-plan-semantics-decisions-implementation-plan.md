---
title: K-PLASMA v2 계획 의미 검토 구현 계획
date: 2026-11-06
status: implemented-with-quality-limitations
implementation_status: implemented-opt-in
scope: graph-v2-only
---

# K-PLASMA v2 계획 의미 검토 구현 계획

> **실행 결과:** 사용자의 구현 승인을 받아 아래 흐름을 구현했다. 정상 계획 오탐이 남아 기본 활성화 기준은 충족하지 못했다. 기본 off·명시적 opt-in으로 두며, [검증 결과](../../verification/2026-11-06-v2-plan-semantics-review.md)를 따른다. 아래 제안·예상 항목은 작성 당시의 계획이며 실제 성공률 보장이 아니다.

**Goal:** 도구 실행 전에 Decisions가 사용자 원문과 실제 실행 계획의 의미를 대조하고, 불일치하면 기존 재계획 경로로 보내 잘못된 조건의 조회·비교를 막는다.

**Architecture:** 기존 코드 검사 다음에 `review_plan` 노드를 추가한다. 코드 검사는 구조·지원 기능·참조·단위를, Decisions는 요구 누락·조건 변경·대상과 연산의 의미를 검사한다. Decisions는 계획을 수정하지 않으며 기존 계획 모델이 수정본을 제출한다. 재계획 한도는 요청 전체 최대 2회를 공유한다.

**Tech Stack:** 기존 Python/Pydantic/LangGraph/httpx, Decisions API, Spring Boot/PostgreSQL/Flyway, React의 진행 기록을 사용한다. 새 라이브러리는 도입하지 않는다.

**Spec:** [v2 설계](../specs/2026-10-31-agent-v2-design.md), [상세 계약](../specs/2026-11-01-agent-v2-contracts.md), [현재 운영 설명](../../development/agent-v2.md), 2026-11-06 대화에서 요청한 실행 전 Decisions 의미 검토.

이 계획의 **추가할 흐름**은 사용자가 요청한 방향이다. 판정 불가·API 장애 처리, 내부 계약과 평가 표본은 아래에서 구체화한 **작성자 제안**이며 아직 구현·성능 검증된 동작이 아니다. 기존 설계의 ‘최초 Decisions 없음’은 구현 시 이 계획의 적용 범위에서 갱신한다.

## 1. 현재 문제와 근거

현재 `agent/python/src/kplasma_agent/v2/plan_validation.py`는 인용 구절이 원문에 존재하는지, 연산자별 필드 형태·단위·참조가 유효한지 검사한다. 인용 구절과 실제 검색 조건이 같은 의미인지는 충분히 검사하지 않는다.

이전에 확인한 실패 유형을 인공 사례로 재구성하면 다음과 같다. 실제 Run·버전·응답 payload는 문서나 fixture에 복사하지 않는다.

| 사용자 요구의 예 | 잘못된 실행 조건 | 현재 검사에서 놓친 부분 |
|---|---|---|
| 에너지 150–160 eV, 두 선택 Run 모두보다 높은 플럭스 | 에너지 `> 0 eV` | 범위 조건이 전혀 다른 조건으로 변경됨 |
| 에너지 150–160 eV인 Run의 IEAD 비교 | 에너지 `= 0 eV` | 비교 도구는 맞아도 검색 집합 자체가 잘못됨 |
| 에너지 9999–10000 eV | 에너지 `= 9999 eV` | 두 조건의 실제 검색 결과가 우연히 모두 0건이어도 의미는 다름 |

계획의 `requirements.text`는 원문을 맞게 설명하면서 `steps.inputs`가 틀릴 수 있다. 검토의 기준은 원문과 실제 실행 필드이며, 모델이 작성한 요구 설명을 정답으로 간주하지 않는다.

현재 구현에서 확인한 연결 지점:

- `graphs/v2.py`: `validate_plan_state`가 통과한 계획을 저장하고 실행으로 보낸다. `replan`은 최초 계획과 같은 `submit_plan` 호출을 사용한다.
- `v2/model_gateway.py`: 현재 Decisions 질문은 `interpretation_scope` 하나이며 질문 충족 여부를 검토 대상에서 제외한다.
- `v2/contracts.py`: 최종 답변의 `ReviewDecision`과 모델 요청 상한 13회가 정의되어 있다.
- `V2ExecutionRepository.java`와 `V13__agent_v2_executions.sql`: 호출 역할에 allowlist와 역할별 상한이 있어 새 역할을 Python에만 추가할 수 없다.
- `AgentPublicEvents.java`와 `AgentProgress.tsx`: 공개 진행 코드도 생산자·소비자를 함께 갱신해야 한다.

## 2. Global Constraints

- v2에만 적용한다. v1, 기본 대화 버전, 기존 대화와 판단 기록을 변경하지 않는다.
- 기존 `submit_plan`, 계획 schema version 1, 세 실행 도구와 내부 계산을 유지한다. 업무 조합을 새 도구로 만들지 않는다.
- 코드 검사 통과와 의미 검사 통과를 구분한다. Decisions 통과가 코드 오류·미지원 단위·확인되지 않은 Run을 허용하지 않는다.
- 재계획은 최초 계획 이후 **요청 전체 합계 최대 2회**, 답변 재작성은 별도 최대 1회다. 자동 도구/API 재시도는 추가하지 않는다.
- 전체 모델 요청 **13회**, 실제 도구 호출 **12회**, 자동 처리 시간 **600초** 상한을 유지한다. 새 검토도 기존 전체 예산을 사용한다.
- 일반 개념 답변은 기존 경로를 유지한다. 조회·수치 비교·그래프에 답변 작성 LLM을 다시 붙이지 않는다.
- 최종 답변에 해석이 있을 때만 실행하는 기존 Decisions 검토와 표시 정책을 유지한다. 새 계획 검토를 그 검토로 대신하지 않는다.
- 원문 조건·정렬·대상·고정 Run 버전을 임의로 바꾸지 않는다. 실제 데이터 부재는 결과 검증과 기존 HITL에서 처리한다.
- 공개 진행 정보에 전체 질문·계획 JSON·모델 내부 추론·비밀값을 추가하지 않는다. 실제 데이터 평가 산출물은 Git에서 제외한 로컬 경로에 둔다.

## 3. 요구사항과 완료 증거

| ID | 요구사항 | 확인할 증거 |
|---|---|---|
| R1 | 최초·수정 데이터 계획은 실행 전에 의미 검토한다. | 검토 PASS 전 단계 예약·도구 호출 0회 |
| R2 | 원문과 `steps.inputs`를 대조하고 누락도 검사한다. | 요구 설명은 맞고 실행 조건만 틀린 fixture를 반려 |
| R3 | 도구 이름을 추측하지 않도록 v2 계약과 확인 문맥을 제공한다. | v2 참조·계산·HITL 정책을 포함한 요청 검사 |
| R4 | 불일치는 기존 재계획으로 전달한다. | 코드 오류와 의미 오류가 재계획 2회를 공유 |
| R5 | 오래된 PASS와 새로고침을 통한 중복 호출을 방지한다. | 수정 계획 재검토, 같은 검토의 저장 결과 복원 |
| R6 | 판정 불가·검토 장애를 성공으로 처리하지 않는다. | 미검토 신규 도구 실행 0회, 정확한 종료 사유 |
| R7 | 계획 검토와 해석 검토를 따로 관측한다. | `PLAN_REVIEW`와 `REVIEW`의 호출·판정·시간 분리 |
| R8 | 정상 계획 오탐과 잘못된 계획 미탐을 함께 평가한다. | 사람 라벨이 있는 정상·오류 계획의 짝 평가 |
| R9 | 일반 개념·HITL·스트리밍·방 이동 회귀를 막는다. | 관련 기존 테스트와 웹 시나리오 통과 |

## 4. 처리 구조와 판정 정책

```text
질문·확인된 Run
    ↓
계획 LLM: submit_plan
    ↓
코드: 구조·지원 기능·의존성·참조·단위 검사
    ├─ 오류 ──────────────────────────────┐
    ↓                                    │
계획 revision 저장                       │
    ↓                                    │
Decisions: review_plan                    │
    ├─ 불일치 / 판정 불가 ────────────────┤
    ├─ 검토 장애 → 신규 실행 중단         │
    ↓ 통과                               ↓
코드: 순차 실행·중간 결과 검사      기존 재계획 LLM
    ↔ 필요한 사용자 선택                 │
    ├─ 복구 가능한 실행 오류 ─────────────┘
    ↓                          수정본은 코드 검사부터 반복
단순 조회·비교: 결과 직접 표시
해석 요청: 기존 답변 LLM → 근거 치환·검사 → 해석용 Decisions
```

### 4.1 Decisions가 판정하는 세 질문

세 질문은 **같은 검토 요청 1회**에 담는다. 검토 질문을 계획 LLM이 만들게 하지 않는다.

| `name` | 검토 기준 |
|---|---|
| `request_coverage` | 원문과 사용자 후속 지시의 조회·비교·그래프·설명·조건 요구가 실제 단계와 답변 경로에 빠짐없이 반영되었는가? |
| `condition_preservation` | 지표·수치·단위 배율·경계 포함 여부·범위·필터·정렬·개수 제한을 보존했는가? 없는 조건을 더하거나 필요한 조건을 삭제하지 않았는가? |
| `target_operation_alignment` | 전체 검색 집합/선택 Run/사용자 선택, 기준 Run, max·min·mean 등 연산과 결과 참조가 질문의 뜻에 맞는가? |

각 질문의 선택지는 `match`, `mismatch`, `unclear`다. 이 단계에서는 미래 데이터가 존재하는지나 실제 계산값이 얼마인지를 판단하지 않는다. 예를 들어 향후 두 Run의 값을 읽어 `max`로 검색 하한을 만들겠다는 계획은 실제 값이 아직 없어도 평가할 수 있다. 필요한 HITL을 올바르게 계획했다면 아직 Run이 선택되지 않았다는 이유로 반려하지 않는다.

최종 해석 검토의 `within_evidence/overclaim/unassessable`과 이름·집계·피드백을 섞지 않는다.

### 4.2 코드가 결정하는 분기

| 상태 | 처리 |
|---|---|
| 세 항목 모두 `match` | 현재 계획의 실행을 허용한다. |
| 하나 이상 `mismatch` | `PLAN_SEMANTIC_MISMATCH`와 실패 항목을 기존 재계획으로 전달한다. |
| `mismatch` 없이 하나 이상 `unclear` | 검토 입력의 필수 구성요소가 코드상 존재하는지 먼저 확인한다. 입력이 완전하면 기존 재계획에 `PLAN_SEMANTIC_UNCLEAR`를 전달해 원문에 근거한 수정 또는 필요한 `await_input`을 계획하게 한다. 입력 자체가 불완전하면 `PLAN_REVIEW_INPUT_INVALID`로 실행을 중단하고 구현 오류로 기록한다. 애매함을 임의 수치·대상으로 채우지 않는다. |
| 요청 실패·응답 파손·질문 누락 | `PLAN_REVIEW_UNAVAILABLE`로 신규 실행을 중단한다. 같은 검토/API를 자동 재호출하거나 장애를 고치기 위해 재계획하지 않는다. |
| 재계획 또는 전체 예산 소진 | 미통과 계획으로 실행하지 않는다. 현재 질문에도 유효한 기존 검증 결과가 있으면 그 결과와 미완료 이유만 제공한다. |

확률·confidence는 기록만 하고 분기는 `choice`로 결정한다. 임의의 0.8/0.9 기준을 새로 도입하지 않는다. `unclear`는 원문이 애매하다는 증명도, 자동으로 사용자를 탓할 근거도 아니다.

오류 계획의 실행을 허용하지 않는 이 정책은, 기존의 ‘최종 해석 검토 미통과 답변도 마지막 답변을 표시’ 정책과 다르다. 후자는 이미 확보한 결과에 대한 표현 정책이며 실행 승인으로 확장하지 않는다.

### 4.3 호출 수와 예산

| 정상 경로 | 현재 | 변경 후 |
|---|---:|---:|
| 데이터 조회·수치 비교·그래프 | 계획 1회 | 계획 1회 + 계획 Decisions 1회 |
| 데이터 결과 해석 | 계획 + 작성 + 해석 Decisions = 3회 | 기존 3회 + 계획 Decisions = 4회 |
| 일반 개념 | 계획 + 작성 = 2회 | 동일 |

`PLAN_REVIEW`의 역할별 상한은 3회다. 최초 계획과 최대 두 수정 계획에 대응한다. 코드 검사에서 탈락한 초안에는 Decisions를 호출하지 않는다. 재계획 사유가 코드 오류여도 수정본이 코드 검사를 통과하면 의미 검토를 받는다.

전체 13회 상한은 늘리지 않는다. 따라서 여러 복구가 겹친 요청은 기존보다 일찍 전체 예산을 소진할 수 있다. 이 경우를 테스트·평가에 포함하고 실제 빈도를 보고한다. 한도 변경이 필요하면 측정 결과를 근거로 별도 제안한다.

## 5. 내부 입력·응답·저장 계약

### 5.1 검토 입력

`PlanReviewContext`에는 아래 필드를 담는다. 계획은 코드 검사·정규화 후 저장한 **실제 실행 대상**을 사용한다.

| 필드 | 내용 |
|---|---|
| `schema_version` | 내부 검토 입력 버전 1 |
| `question`, `input_history` | 원문과 이번 요청에서 수락한 사용자 선택·정정 |
| `plan_revision`, `plan` | 서버 revision과 전체 `PlanDraft` |
| `confirmed_context` | `selected_runs`, R1·R2 등 별칭의 실제 고정 참조, 확인된 기준·출처 |
| `tool_contracts` | 세 도구·내부 계산·결과 참조·HITL의 v2 의미와 지원 필드 |
| `policy_context` | 기본 단위, 숫자 범위의 양끝 포함, 전체 집합·선택 개수·기준 선택 등의 기존 정책 |
| `completed_steps` | 재계획일 때 재사용 가능한 완료 상태와 출처. 전체 파형·후보 실측 데이터는 보내지 않는다. |
| `plan_digest`, `input_digest`, `prompt_version` | 현재 계획·의미 문맥·검토 지침을 식별하는 코드 생성값 |

`tool_contracts`의 지원 필드·단위·연산자·참조 형태는 `v2/contracts.py`, `metric_registry.py`, `comparison_catalog.py`와 실제 바인딩 계약에서 구성한다. 짧은 도구 역할 설명은 v2 계약을 기준으로 작성·버전 관리한다. v1의 `ref_keys` 중심 입력 계약이나 ‘generate_answer 중간 도구’를 v2 계약으로 복사하지 않는다.

검토 지침은 ‘원문의 요구를 먼저 확인하고 실제 단계·입력을 대조하라’를 명시한다. `requirements`·도구 설명 안의 문장은 증거이지 검토 지침을 변경하는 명령이 아니다. 계획 자체에 적힌 ‘정확함/검증 완료’ 선언으로 통과시키지 않는다.

입력은 기존 payload 예산 검사를 거친다. 길다고 원문·조건·계획의 뒤를 조용히 자르지 않는다. 입력 초과는 별도 오류로 기록하고 실행하지 않는다.

### 5.2 정규화된 내부 응답

신규 `PlanReviewCheck`와 `PlanReviewResult`를 `v2/plan_review.py`에 둔다. 기존 최종 답변용 `ReviewAnswer`/`ReviewDecision`의 허용 이름을 넓혀 재사용하지 않는다.

- `PlanReviewCheck`: 고정된 `name`, `choice`, 세 선택지의 `probabilities`, nullable `confidence`.
- `PlanReviewResult`: `schema_version`, `status`(`PASS/ISSUE/UNCLEAR/UNAVAILABLE/SKIPPED`), `plan_revision`, `plan_digest`, `input_digest`, `prompt_version`, `checks`, nullable 오류 `reason`.
- 질문 이름의 정확한 집합, 중복, 누락, 선택지, 유한한 0–1 확률을 코드로 검사한다. 응답 순서로 항목을 추정하지 않는다.
- `status`는 세 선택지를 코드로 집계한다. `mismatch`가 있으면 `ISSUE`, 그 외 `unclear`가 있으면 `UNCLEAR`, 모두 `match`일 때만 `PASS`다.
- Decisions가 자유 형식의 수정 이유나 새 계획 JSON까지 반환한다고 가정하지 않는다. 실패 항목과 원문·기존 계획을 재계획 모델에 넘긴다.
- HTTP/파싱 오류는 `UNAVAILABLE`이며 의미 불일치와 구분한다. 상세 로그에는 정제된 오류 종류와 HTTP 상태만 남기고 인증값·응답 본문을 무분별하게 출력하지 않는다.

### 5.3 재계획·재개·중복 방지

- 저장 역할은 `PLAN_REVIEW`, 검토 예약 키는 요청 안에서 계획 revision·검토 입력 digest·지침 버전에 연결한다. 기존 예약 키 길이 200자 안에서 코드가 만든다.
- 검토 결과를 저장한 뒤에만 PASS를 그래프 상태에 반영한다. 코드 검사 통과로 저장된 plan revision을 곧바로 실행 승인으로 보지 않는다.
- `execute_step` 진입 시 현재 계획 digest에 맞는 PASS를 확인한다. 이전 revision의 PASS, 다른 질문·선택 문맥의 PASS로 통과하지 않는다.
- 새 계획을 수락하면 이전 계획 검토 상태를 무효화한다. 재계획으로 단계의 의미가 바뀌면 기존 결과 재사용도 기존의 단계·입력·의존성 일치 규칙을 따른다.
- 새로고침·worker 복구는 같은 예약에 저장된 응답을 복원한다. 미저장 응답의 결과가 불명확한 경우 동일 API를 재전송하지 않고 미완료로 남긴다.
- 계획에 이미 승인된 `await_input`을 사용자가 정상적으로 채우면 같은 계획을 다시 의미 검토하지 않는다. 선택 Run의 후보 집합·정확한 개수·버전·기준은 기존 코드 검사가 확인한다. 이때 허용된 확인 단계 출력만 바뀌었음을 기록한다.
- `input_digest`의 기준 문맥은 검토 시점에 고정한다. 이후 입력을 전부 무시하는 것이 아니라, 현재 pending 단계가 허용한 구조화 선택만 그 승인 범위에서 받아들인다. 임의의 문맥 변경이나 자유 텍스트는 같은 digest로 취급하지 않는다.
- 자유 텍스트로 조건·대상 의도를 바꾸거나 계획 밖의 입력을 바꾸면 이전 PASS를 재사용하지 않는다. 기존 재계획 경로를 거쳐 새 의미 검토를 받는다.
- 취소·lease 만료·대화 epoch 변경 뒤의 늦은 응답은 기존 서버 fencing으로 거절한다. 검토 완료가 종료된 요청을 다시 실행시키지 못한다.

## 6. Review Focus

1. **요구 설명만 정상인 계획:** `requirements.text`는 150–160인데 실제 조건은 `> 0`인 경우를 Task 1·2·4·6에서 검사한다.
2. **우연히 같은 검색 결과:** `between 9999–10000`과 `eq 9999` 모두 실제 데이터에서는 0건이어도 다르게 판정해야 한다. Task 6에서 인공 중간값 9999.5로 정답을 분리한다.
3. **HITL과 미래 데이터:** 아직 선택하지 않은 Run이나 미실행 결과 참조를 의미 오류로 오인하지 않아야 한다. Task 1·4·5에서 정상 선택 계획을 통과시키고 선택 뒤 중복 검토를 막는다.
4. **오래된 승인 재사용:** revision 변경·자유 텍스트 정정·worker 교체 후 과거 PASS가 새 실행을 열지 않아야 한다. Task 3·4에서 검증한다.
5. **관측과 실제 동작의 혼동:** ‘검토 호출 완료’ 이벤트를 PASS로 표현하지 않고, 해석 검토와 카운터를 섞지 않는다. Task 3·5·6에서 검증한다.

추가 한계: 초기 적용 대상은 코드 검사를 통과한 `data_request` 계획이다. 실제 데이터 요청을 `general_only`로 잘못 분류하는 문제 전체를 이번 기능으로 해결했다고 주장하지 않는다. 기존 데이터 경로 우회 검사는 유지하고 해당 분류 오류는 별도 평가 항목으로 남긴다. 일반 개념까지 매번 Decisions를 호출하는 범위 확장은 포함하지 않는다.

## 7. 작업 순서와 구현 단위

모든 task의 RED/GREEN은 **구현 시 실행할 절차**다. 이 계획서 작성 중 테스트를 실행했다는 뜻이 아니다. 변경 전 기존 테스트를 기준으로 실패 사례를 추가하고, 의미 있는 기능 단위로 커밋한다. 현재 미커밋 UI 변경은 별도 작업으로 보존한다.

### Task 1. 검토 입력·질문·판정 계약

**Files:** Create `agent/python/src/kplasma_agent/v2/plan_review.py`, `agent/python/tests/v2/test_plan_review.py`. Read `agent/python/src/kplasma_agent/v2/contracts.py`, `agent/python/src/kplasma_agent/v2/bindings.py`, `agent/python/src/kplasma_agent/metric_registry.py`, `agent/python/src/kplasma_agent/comparison_catalog.py`.

**Interfaces:** `build_plan_review_context(plan, revision, question, input_history, confirmed_context, completed_steps) -> PlanReviewContext`; `PLAN_REVIEW_QUESTIONS`; `PlanReviewResult`; `plan_review_feedback(result) -> dict`. 이 이름과 필드를 후속 task에서 그대로 사용한다. digest 생성과 현재 계획과의 일치 확인도 이 모듈의 순수 함수로 둔다.

- [ ] **RED:** 원문 보존, 세 질문 고정, 실제 `steps.inputs` 포함, v2 도구 계약, nullable 기본 단위, Run 버전, 승인된 선택 자리표시자, digest 변경에 관한 실패 테스트를 작성·실행한다.
- [ ] **구현:** 순수 입력 구성·응답 타입·집계·피드백을 추가한다. 원문 의미를 완전히 파싱하는 새 정규식 엔진이나 별도 요구조건 추출 LLM은 만들지 않는다. 현재 계획 프롬프트는 바꾸지 않아 추가 검토의 효과를 분리한다.
- [ ] **GREEN:** `test_plan_review.py`와 기존 `test_plan_validation.py`, `test_contracts.py`를 실행한다. 최종 답변 계약은 그대로 파싱되어야 한다.
- [ ] **커밋 단위:** `feat(agent): define v2 plan semantics review contracts`.

### Task 2. Decisions 계획 검토 호출

**Files:** Modify `agent/python/src/kplasma_agent/v2/model_gateway.py`, `agent/python/src/kplasma_agent/v2/budget.py`, `.env.example`; extend `agent/python/tests/v2/test_model_gateway.py`; Create `agent/python/tests/v2/test_budget.py`.

**Interfaces:** `V2ModelGateway.review_plan(context) -> (result_dict, usage_or_none)`. 기존 `review(context)`는 해석 검토 전용으로 유지한다. Task 1의 타입과 세 질문을 사용한다.

- [ ] **RED:** 한 HTTP 요청의 JSON 입력·세 질문, 질문별 `choice` 사용, 낮은 confidence도 판정값을 따르는 동작, 질문 누락·중복·미지 선택지·확률 파손·429·timeout·입력 초과를 검사한다. 해석 질문이 계획 요청에 섞이지 않아야 한다.
- [ ] **구현:** 기존 Decisions 모델·URL·인증 설정을 사용해 계획 검토용 메서드를 추가한다. `review_answer`의 고정된 최종 해석 질문에 새 항목을 붙이지 않는다. 검토 payload 전체를 API 호출 전에 검사하고 숨겨진 재시도는 두지 않는다.
- [ ] **설정:** `AGENT_V2_PLAN_REVIEW_ENABLED` 하나를 추가하며 새 v2 실행에서는 기본 활성화한다. 비활성화는 비교 평가·롤백용이며 검토 SKIPPED와 설정 상태를 기록한다. 실행 중인 요청에서는 설정을 고정한다. 모델은 기존 Decisions 설정을 사용한다.
- [ ] **GREEN:** `agent/python/tests/v2/test_model_gateway.py`, `agent/python/tests/v2/test_plan_review.py`, `agent/python/tests/v2/test_budget.py`를 실행한다. 기존 해석 검토·스트리밍 호출 형식 회귀를 확인한다.
- [ ] **커밋 단위:** `feat(agent): evaluate plan semantics with Decisions`.

### Task 3. 호출 예약·저장과 백엔드 호환성

**Files:** Modify `backend/src/main/java/com/kplasma/analysisagent/agent/v2/V2ExecutionRepository.java`; Create `backend/src/main/resources/db/migration/V18__agent_plan_review_attempts.sql`; extend `backend/src/test/java/com/kplasma/analysisagent/workspace/AgentGraphVersionTest.java`; update `docs/contracts/agent-v2.openapi.json`의 내부 모델 역할 설명.

**Interfaces:** 기존 `reserve_model(kind, key)`와 `complete_model(attempt_id, outcome)`를 그대로 사용하며 새 kind는 `PLAN_REVIEW`다. 공개 최종 답변 schema에 계획 검토 결과를 끼워 넣지 않는다.

- [ ] **RED:** PLAN_REVIEW 3회 상한, 요청 전체 13회 공유, 같은 키의 저장 결과 복원·중복 호출 거절, 다른 역할·입력 revision 충돌, 취소·lease 만료 후 완료 거절을 검사한다.
- [ ] **구현:** 역할 allowlist와 DB CHECK를 새 마이그레이션으로 확장한다. 적용된 V9를 수정하지 않는다. 구현 시작 시 최신 번호가 V18을 사용 중이면 다음 번호를 사용한다. 검토 결과의 digest·판정·usage는 기존 모델 outcome에 저장한다.
- [ ] **GREEN:** PostgreSQL 마이그레이션이 기존 계획·모델 기록을 보존하는지와 위 테스트를 확인한다. 기존 v1 요청·v2 예약·단계 불변성 회귀도 실행한다.
- [ ] **커밋 단위:** `feat(backend): persist bounded plan review attempts`.

### Task 4. 그래프 실행 게이트와 기존 재계획 연결

**Files:** Modify `agent/python/src/kplasma_agent/graphs/v2.py`; extend `agent/python/tests/v2/test_graph.py`, `test_streaming_graph.py`, `test_executor.py`에서 영향을 받는 호출 순서·복구 테스트.

**Interfaces:** 신규 상태 `plan_review`, `plan_review_input`, `plan_review_feedback`, `plan_review_enabled`. 최종 해석 상태 `review`와 분리한다. 코드 검증 후 `review_plan`으로 분기하고, `request_plan`은 의미 피드백과 수정할 전체 계획을 전달한다. 검토 활성화 여부를 요청 시작 시 checkpoint에 고정해 재개 중 설정 변경으로 우회하지 못하게 한다.

- [ ] **RED:** 정상 통과, ISSUE→수정→재검토→실행, 코드 오류와 의미 오류의 한도 공유, 2회 이후 중단, UNCLEAR→명확화 계획, UNAVAILABLE→신규 실행 0회를 검사한다.
- [ ] **RED:** 이전 PASS 이후 계획 조건 변경, stale digest, 같은 checkpoint 복원, pending 모델 결과 불명확, 선택·기준 HITL의 정상 재개, 자유 텍스트 조건 정정, 실제 결과 부재를 의미 오류로 재시도하지 않는 경우를 검사한다.
- [ ] **구현:** 검토 활성 요청은 저장된 PASS와 현재 계획을 코드로 대조한 뒤에만 실행한다. 평가·롤백을 위해 요청 시작부터 명시적으로 비활성화한 경우만 SKIPPED로 실행하고 PASS로 기록하지 않는다. 기존 `guard_replan`·카운터·유효 결과 재사용을 사용한다. 일반 개념과 단순 데이터 표시의 답변 작성 경로는 유지한다. 검토 활성 요청에서 유효 PASS 없이 executor로 진입하는 우회 경로도 막는다.
- [ ] **종료 안내:** 결과가 없으면 ‘확인된 결과를 표시합니다’라고 쓰지 않는다. 계획을 확정하지 못함, 검토 연결 실패, 실제 데이터 부재를 분리한다. 기존 검증 결과가 있으면 현재 질문에 유효한 결과만 제공한다.
- [ ] **GREEN:** v2 그래프·executor·스트리밍 테스트와 v1 그래프 회귀를 실행한다. 단순 조회는 `PLAN_INITIAL, PLAN_REVIEW`만, 일반 개념은 기존 `PLAN_INITIAL, COMPOSE`만 사용해야 한다.
- [ ] **커밋 단위:** `feat(agent): gate v2 execution on plan semantics review`.

### Task 5. 진행 기록과 테스트용 실행기의 생산자·소비자 연결

**Files:** Modify `agent/python/src/kplasma_agent/graphs/v2.py`, `backend/src/main/java/com/kplasma/analysisagent/agent/AgentPublicEvents.java`, `frontend/src/features/agent/AgentProgress.tsx`; extend `agent/python/tests/test_progress.py`, `backend/src/test/java/com/kplasma/analysisagent/agent/AgentPublicEventPayloadTest.java`, `frontend/src/features/agent/agent-progress.test.tsx`, `frontend/src/features/agent/progress-events.test.ts`; update `agent/python/tests/runtime_v2_worker.py`와 `agent/python/evals/v2_harness.py`의 테스트용 모델 구현.

**Interfaces:** 공개 activity code `PLAN_REVIEW`를 추가한다. 이벤트 envelope와 최종 snapshot schema는 유지한다. 현재 `code: string` 소비자에 불필요한 wire 버전 변경을 추가하지 않는다.

- [ ] **RED:** 새 코드가 서버 allowlist·화면 매핑을 통과하고, 계획 검토와 해석 검토 문구가 구분되는지 검사한다. 검토 장애·ISSUE를 PASS라고 표현하지 않아야 한다.
- [ ] **구현:** 시작 문구는 ‘질문 조건과 작업 계획을 대조하는 중’, 완료 문구는 ‘작업 계획의 의미 검토를 마쳤어요’로 한다. 기존 회색 14px·접힘·종료 시간 요약을 그대로 사용한다. 검토 요청을 마쳤다는 사실과 검토 통과를 구분한다.
- [ ] **테스트 모델:** scripted gateway가 명시적으로 `review_plan` 응답을 제공하게 한다. 실제 gateway에 메서드가 없거나 호출이 실패했을 때 자동 PASS로 대체하는 호환 코드는 넣지 않는다.
- [ ] **GREEN:** 진행·이벤트·타입 검사와 브라우저 회귀를 실행한다. 390/800/1008/1440px에서 잘림·입력·가로 넘침·스크롤 위치를 확인한다. 검토 도중 취소·새로고침·방 이동도 확인한다.
- [ ] **커밋 단위:** `feat(frontend): distinguish plan review progress`.

### Task 6. 고정 계획 검증과 실제 웹 평가, 문서 갱신

**Files:** Create `agent/python/evals/plan_review_cases.py`, `agent/python/evals/run_plan_review.py`, `agent/python/evals/test_plan_review_eval.py`; extend `agent/python/evals/v2_cases.py`, `v2_harness.py`, `test_v2_harness.py`, `run_v2.py`, `agent/python/evals/README.md`, `frontend/e2e/agent-v2-live.spec.ts`. Update v2 설계·상세 계약·`docs/development/agent-v2.md`와 내부 모델 역할 계약 문서.

**Interfaces:** 고정 계획 평가의 각 사례는 인공 질문·확인 문맥·정상 계획·오류 계획·사람이 정한 항목별 기대 판정과 경계값을 가진다. 기본 runner는 실행 목록만 출력하고 `--live`일 때만 API를 호출한다. 기존 v2 runner에도 계획 검토 on/off와 결과별 호출 역할·시간을 기록한다.

- [ ] **RED:** 같은 질문에 대한 정상·오류 계획을 분리 채점하고, 초기 계획 의미·검토 판정·수정 계획 의미·최종 결과를 별도 필드로 보고하는 테스트를 작성한다. 한 계획 문자열이나 step ID의 정확한 일치만으로 채점하지 않는다.
- [ ] **구현:** 아래 표본과 평가 지표를 적용한다. 인공 경계값을 실행해 검색 조건과 연산 의미를 확인하며, Decisions PASS를 정답 라벨로 다시 쓰지 않는다. 기존 네 개 인공 Run의 값을 바꿔 기존 평가 정답을 깨지 않고, 새 범위·경계 사례에는 격리한 인공 데이터 묶음을 추가한다.
- [ ] **문서:** 기존 ‘최초 Decisions 없음’, ‘단순 조회에는 Decisions 없음’은 계획 검토와 최종 해석 검토를 구분해 갱신한다. 예산·장애 종료·설정·진행 문구·검토 한계를 함께 기록한다.
- [ ] **GREEN:** 평가 채점기 테스트, 관련 계약·Python/Java/TS 테스트, 격리 웹 시나리오를 확인한 뒤 실제 API 평가를 실행한다. 실제 로컬 앱 평가 시 백엔드·worker·프론트엔드를 필요한 범위에서 재실행하고 먼저 v2 연결 상태를 확인한다.
- [ ] **적용 순서:** DB 마이그레이션·백엔드의 역할/이벤트 수용을 먼저 배포하고, 화면 문구를 준비한 뒤 새 worker에서 검토를 활성화한다. 롤백은 새 요청의 검토 설정이나 애플리케이션 버전으로 하며, 저장한 검토 기록·대화·마이그레이션을 삭제하지 않는다. 진행 중 요청에 고정한 검토 설정은 뒤집지 않는다.
- [ ] **커밋 단위:** 평가 코드와 계약 문서를 기능별로 나눈다. 실제 응답·원본 계획 로그·DB·스크린샷은 커밋하지 않는다.

## 8. 평가 표본과 합격 기준

### 8.1 고정 계획: 검토기가 문제를 실제로 잡는가

같은 질문에 대해 **정상 계획 1개와 의미 오류 계획 1개**를 사람이 작성한다. 코드 형식 검사는 둘 다 통과하게 만들어 추가 검토의 효과를 분리한다.

| 번호 | 오류 계획에서 바꾸는 부분 |
|---|---|
| P01 | 150–160 범위를 `> 0`으로 변경 |
| P02 | 150–160 범위를 `= 0`으로 변경, 후속 IEAD 비교는 정상 유지 |
| P03 | 9999–10000 범위를 `= 9999`로 변경 |
| P04 | 압력·플럭스 복합 필터 중 압력 삭제 |
| P05 | 50 이상을 50 초과로 변경 |
| P06 | 0.008 Torr를 값만 바꾸거나 배율을 틀리게 전달 |
| P07 | 두 Run 모두보다 높은 조건을 max 대신 mean으로 계산 |
| P08 | 전체 검색 결과 비교를 임의 두 후보 비교로 축소 |
| P09 | ‘그중 두 개’에 선택 확인 없이 두 후보를 자동 선택 |
| P10 | 범위 안 Flux 내림차순을 반대로 정렬 |
| P11 | 사용자가 직접 고를 기준을 임의 R1로 확정 |
| P12 | 서로 독립적인 두 범위 검색을 하나의 집합 조건으로 합침 |

**검토 요청 계획:** 12종류 × 정상·오류 2개 × 각각 3회 = **72회**. 계획 생성 LLM은 이 단계에서 호출하지 않는다. 정상/오류 각 36회이며 매번 같은 입력을 사용한다. 이는 72개 사용자 질문이나 전체 Agent 실행 72회를 뜻하지 않는다.

원문 범위와 틀린 조건을 구별하는 인공 경계값은 149.9, 150, 155, 160, 160.1 및 9999.5 등을 사용한다. 두 Run의 인공 플럭스가 10·20이면 ‘둘 모두보다 높게’의 하한은 20이고, 평균 15를 쓰는 계획은 다른 의미다. 이 값은 실제 실험 결과가 아니다.

**초기 회귀 기준:** P01–P03의 오류 계획이 한 번이라도 PASS면 미해결이다. 전체 표본에서 오류 미탐과 정상 오탐을 각각 공개하고, 정상 짝까지 모두 반려하는 검토기는 개선으로 보지 않는다. 기본 활성화를 완료했다고 보고하려면 고정 표본의 잘못된 통과·불필요한 반려·판정 불가가 없어야 한다. 이것은 작은 회귀 표본의 기준이며 운영 정확도 100%의 증명이 아니다.

### 8.2 실제 웹: 수정 후 질문을 끝까지 처리하는가

아래 여섯 흐름을 검토 off/on에서 각각 3번 실행한다. **6종류 × 두 설정 × 3회 = 36개 Agent 실행**이며, 내부 모델 호출 수는 재계획·해석 유무에 따라 달라진다.

1. 선택한 두 Run 모두보다 높은 Flux와 150–160 eV 필터의 중첩 검색.
2. 150–160 eV 검색 집합 전체의 IEAD 특징값·선택 히트맵 비교.
3. 9999–10000 eV의 정상 0건 처리. 0건만으로 계획이 맞다고 채점하지 않는다.
4. 압력 하한과 Flux 하한을 함께 적용한 전체 IAD 비교. Bias-off는 실제 비가용으로 구분한다.
5. 필터 후 정확히 두 Run 선택, 검색 순서·필터 측정값·기준 선택을 유지한 비교 재개.
6. 선택 Run의 전위 비교와 원인 해석. 기존 최종 해석 검토가 별도로 실행되는지 확인.

같은 모델·추론 수준·도구·질문·고정 데이터·계획 프롬프트를 유지한다. 검토 off/on에서 새로 생성된 최초 계획은 달라질 수 있으므로, 이 실험만으로 차이를 모두 검토기의 효과라고 단정하지 않는다. 검토 자체의 효과는 8.1의 같은 계획을 사용한 평가로 판단한다.

별도 회귀로 일반 개념의 수식 스트리밍, API 장애, 재계획 한도, 검토 도중 취소·방 이동·새로고침을 확인한다. 자동화된 인공 데이터 E2E와 실제 Run을 쓰는 로컬 웹 확인의 결과를 섞지 않는다. 실제 Run 확인은 사용한 데이터 버전과 기준 정답을 고정하되 산출물은 비공개 로컬에 둔다.

### 8.3 보고할 항목

- 잘못된 계획이 통과한 수 / 잘못된 계획 수, 정상 계획이 반려된 수 / 정상 계획 수, 판정 불가 수, API 장애 수.
- 최초 계획의 정확성, 재계획으로 수정된 비율, 최종 질문 수행 여부를 각각 구분한다.
- 조건·경계·단위·전체 집합·선택 개수·연산·기준 Run의 정답 여부를 코드 oracle과 사람 라벨로 확인한다.
- 계획·계획 검토·도구·답변 작성·최종 해석 검토의 호출 수와 시간, 최초 결과 표시와 전체 완료 시간을 구분한다.
- 이탈·실패 사례마다 원문, 최초 계획, 코드 검사 결과, 검토 항목별 판정, 전달한 피드백, 수정 계획, 실제 실행 입력을 로컬에서 연결한다.
- 리뷰 장애나 제공자 장애를 모델의 의미 오류로 합산하지 않는다. 오류 로그가 원인을 확정하지 못하면 추정과 확인 사실을 나눈다.

## 9. 검증 계약과 완료 조건

구현 후 실행할 주요 검증은 다음과 같다. 정확한 테스트 파일 선택은 각 task에 명시한 소유 범위를 따른다.

```sh
uv run --project agent/python --frozen pytest agent/python/tests/v2 agent/python/tests/test_progress.py -q
uv run --project agent/python --frozen pytest agent/python/evals/test_plan_review_eval.py agent/python/evals/test_v2_harness.py -q
backend/gradlew -p backend test --tests '*AgentGraphVersionTest' --tests '*AgentPublicEventPayloadTest' --tests '*V2ContractTest' --console=plain
npm run typecheck -w frontend
npm run test -w frontend
npm run test:e2e:v2
```

- [ ] R1–R9와 Review Focus를 각 소유 task의 테스트로 확인하고 결과를 검증 기록에 남겼다.
- [ ] 고정 계획 검토와 실제 웹 평가를 구분해 실행·보고했다. 각 실패를 모델·검토 입력/지침·그래프 분기·API 장애로 구분했다.
- [ ] 원문과 다른 계획은 미통과 상태로 도구를 실행하지 않았다. 정상 계획·정상 HITL을 괜히 막지 않았다.
- [ ] v1, 일반 개념, 단순 결과 표시, 기존 해석 검토, 과거 대화 복원에 회귀가 없다.
- [ ] 저장·복구·취소·권한/lease 경계와 전체 예산을 지켰다. 실제 데이터가 Git에 포함되지 않았다.
- [ ] 검토 완료와 검토 통과, 계획 검토와 해석 검토를 사용자 문구·로그·보고서에서 구분했다.

## 10. 계획 자체 점검과 남는 한계

계획 자체 점검: R1–R9의 소유 task, 내부 타입·gateway·예약 역할·그래프 상태·공개 이벤트의 생산자와 소비자, 데이터 미보유와 판정 불가의 구분, 기존 예산과 사용자 선택 재개를 문서상 대조했다. 이 점검은 실제 테스트나 독립 모델 리뷰의 통과 보고가 아니다.

남는 한계는 다음과 같다.

- Decisions도 모델 판단이므로 의미 오류와 오탐이 모두 가능하다. 별도 API 호출이 서로 다른 모델의 완전한 독립성을 보장하지 않는다.
- 정상 데이터 요청의 검토 호출이 1회 추가된다. 실제 지연·비용 감소나 전체 정확도 향상은 평가 전에는 확정할 수 없다.
- 세 선택형 판정은 문제 유형을 알려 주지만 자유 형식의 상세 수정 이유를 생성하지 않는다. 처음에는 추가 설명 LLM 없이 전체 원문·계획과 실패 항목을 기존 재계획 모델에 전달한다.
- 사용 가능한 근거가 없거나 실제 요구가 애매한 상황은 검토기를 통과시키기 위한 임의 보정으로 해결하지 않는다.

## 11. 참고 자료

- [OpenAI Decisions 공식 가이드](https://developers.openai.com/api/docs/guides/decisions): JSON 입력, 선택형 판정, 여러 질문의 동시 평가, 확률·confidence 반환을 확인했다. 이 문서가 K-PLASMA 계획 의미 검토의 정확도를 입증하는 것은 아니다.
- [v2 설계](../specs/2026-10-31-agent-v2-design.md), [상세 계약](../specs/2026-11-01-agent-v2-contracts.md), [기존 구현 계획](2026-11-01-agent-v2-implementation-plan.md).
- [진행 기록·스트리밍 계획](../../plans/2026-11-05-001-feat-agent-progress-and-answer-streaming-plan.md), [운영·평가 설명](../../development/agent-v2.md).

현재 상태: **구현·DB 적용·재실행·평가를 수행했다. 코드 테스트는 통과했지만 정상 계획 오탐이 남아 기본 활성화는 보류했다.** 12쌍 72회에 복합 선택 회귀 1쌍을 추가한 최종 78회와 실제 웹 36회 결과는 검증 문서에 기록했다. 실제 Run·원문 모델 응답·스크린샷·DB 백업은 Git 제외 로컬 경로에만 보관한다.

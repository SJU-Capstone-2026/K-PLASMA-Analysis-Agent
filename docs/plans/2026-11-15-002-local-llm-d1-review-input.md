---
title: "d1 검토 입력 축약과 정확도·시간 비교 계획"
date: 2026-11-15
type: perf
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# d1 검토 입력 축약과 정확도·시간 비교 계획

## Goal Capsule

**먼저 읽을 요약:** d1에 보내는 도구 설명과 중복 정보를 줄여 보되, 원본 계획·검사·응답은 보존한다. 줄일 수 있는 양이 작으면 모델 평가 전에 중단하고, 빨라져도 기존에 맞히던 검사를 새로 틀리면 적용하지 않는다. 이번 요청에서는 이 계획서만 작성하며 구현·모델 호출·설정 변경은 하지 않는다.

- 목표: 현재 M4 Pro 24GB에서 검토 품질을 떨어뜨리지 않고 d1 검토 시간을 줄일 후보를 만든다. 20% 시간 단축은 검증할 목표이며 예상 성과가 아니다.
- 적용 범위: `v2_localLLM`의 **계획 의미 검토 입력**만 대상이다. 기존 v2/v3, Qwen 계획 작성, 답변 검토·최종 응답, 그래프 노드·연결·HITL은 보호한다.
- 고정 조건: Docker VM 1536MiB, d1 검토 ON, 기존 모델·정밀도·입력 한도·재계획/재작성 예산을 유지한다.
- 실행 권한: 이 문서의 준비 상태는 계획의 구체성을 뜻한다. 사용자의 “아직 구현하지 말 것”을 해제하지 않는다. commit/push·PR·기본 설정 승격·구조 대안 구현도 자동 후속 작업에 포함하지 않는다.

## Product Contract

### Problem and evidence

독립 4개 배치는 기존 개별 MLX 검토와 결과는 같았지만 전체 계산량을 줄이지 못했다. 최근 GPU 진단의 **11검사 인공 입력 한 건**에서는 모델 로딩을 제외한 처리 시간이 개별/독립4 모두 약 28.64초, GPU busy 약 100%였다. 이는 전체 DRAM 대역폭 포화보다 GPU 실행 경로의 제약을 시사하지만, ALU·캐시·개별 커널 병목을 확정한 측정은 아니다.

그때 사용한 공통 입력은 4,108토큰이었다. 이번 계획 조사에서는 **추론 없이 기존 로컬 tokenizer로만** 하위 구성을 확인했다.

| 구성 | 토큰 수 | 해석 |
|---|---:|---|
| 사용자 질문 | 33 | 질문 자체가 길어서 느린 사례는 아님 |
| 원본 계획 | 396 | 그대로 보존 |
| 전체 도구 계약 | 2,318 | 모두 불필요한 설명은 아님 |
| 그중 `compare_runs` 지표 32개 메타데이터 | 1,365 | 이름·단위·계산 정의가 있어 함부로 삭제 불가 |
| 정책 지침 | 467 | 단위·범위·선택 등 의미 검토 규칙이므로 보존 |
| `check_specs` | 370 | 기존 목록 그대로 보존 |
| `execution_view` | 297 | 계획의 다른 표현이지만 d1 판단을 돕는 정보일 수 있음 |
| `program_effects` | 90 | 사람이 읽기 쉬운 실행 설명으로 보존 |

토큰 수는 같은 인공 입력의 독립 하위 직렬화 값이며 경계 토큰 때문에 단순 합산하지 않는다. 공통 입력 4,108과 엔진 템플릿을 포함한 prefix 4,115도 다른 수치다. 비교 지표 정의의 동일 문장 반복분은 텍스트만 계산하면 약 **387토큰**이다. 참조·공통 사전을 추가하는 비용을 빼기 전 값이므로 실제 절감량이 아니다. **2,318토큰 대부분을 안전하게 삭제할 수 있다는 전제로 진행하지 않는다.**

현재 공용 기본 경로는 llama.cpp Q8 개별 처리로 복구되어 있다. 위 GPU 수치는 MLX BF16 진단이며 Q8의 새 성능 기준으로 사용하지 않는다. 과거 MLX B/D의 4/8은 상태 정답률이고, 잘못된 이유로 ISSUE가 된 사례도 있다. 기존 웹 앞 5문항 통과, d1 오류 탐지, 상용 Decisions 80/80은 서로 다른 평가다.

### Requirements

- R1. 사용자 질문·입력 이력·확정 문맥·Qwen 원본 계획·정책 지침·`check_specs`·`program_effects`·선택값/단위/경계/참조 출처는 보존한다. Qwen이나 다른 LLM으로 요약하지 않는다.
- R2. 검사 ID·개수·순서·검사 지침·선택지 문자열, 응답 완전성 검사, PASS/ISSUE/UNCLEAR/UNAVAILABLE 집계와 확률 해석은 유지한다. 검사를 합치거나 건너뛰지 않는다.
- R3. 원본 검토 snapshot·digest·원문 근거·계획 경로·재계획 피드백을 유지한다. 그래프, `submit_plan` 스키마, 최종 응답·스트리밍·저장 형식은 바꾸지 않는다.
- R4. 토큰을 세는 입력과 실제 d1에 보내는 입력이 정확히 같아야 한다. 전송 표현 버전은 설정 fingerprint와 준비 증거에 연결한다.
- R5. 축약 전후를 같은 엔진·정밀도·검사 방식으로 비교하고, 판정·검사별 이유·시간·메모리를 각각 보고한다. 원래 오답을 고친 결과와 새 회귀를 상쇄하지 않는다.
- R6. Docker 1536MiB, 실제 그래프 `plan_review_enabled=true`, 요청 전체 재계획 최대 2회·필요한 답변 검토와 재작성 최대 1회를 유지한다. development 정책의 warning 기록·허용과 critical/미지 상태 중단을 유지한다.
- R7. 의미 정보의 삭제·손상, 새 오승인/오반려, 효과 부족 시 full 입력을 유지하고 구조 대안을 보고한다. 상용 모델 fallback, 외부 원문 전송, OS 인터넷 차단을 추가하지 않는다.

## Planning Contract

### Approach and examples

우선 **정보를 남긴 채 표현의 반복을 줄이는 후보**를 만든다. 정보가 코드상 복원 가능해도 모델이 참조를 이해하지 못할 수 있으므로, 이를 정확도 동등성의 증명으로 취급하지 않는다. 아래 예시는 저장된 실제 데이터가 아닌 기존 소프트웨어 계약의 표현 예다. d1 내부 입력 표현만 달라지며 사용자의 계획 필드나 최종 응답 필드를 바꾸는 예가 아니다.

**후보 1: 반복되는 지표 정의를 한 번만 적는다.**

현재는 여러 지표에 같은 정의 문장이 반복된다.

```json
{
  "ied.maximum": {
    "label": "IED 최대 강도", "unit": "a.u.", "plotId": "ied",
    "definition": "전체 원본 격자에서 계산; 공동 극값 위치는 첫 원본 위치"
  },
  "iad.maximum": {
    "label": "IAD 최대 강도", "unit": "a.u.", "plotId": "iad",
    "definition": "전체 원본 격자에서 계산; 공동 극값 위치는 첫 원본 위치"
  }
}
```

축약 후보는 `tool_contracts.compare_runs` 안에 공통 정의 사전을 두고 연결한다.

```json
{
  "field_definitions": {
    "grid_first": "전체 원본 격자에서 계산; 공동 극값 위치는 첫 원본 위치"
  },
  "fields": {
    "ied.maximum": {
      "label": "IED 최대 강도", "unit": "a.u.", "plotId": "ied", "definition_ref": "grid_first"
    },
    "iad.maximum": {
      "label": "IAD 최대 강도", "unit": "a.u.", "plotId": "iad", "definition_ref": "grid_first"
    }
  }
}
```

32개 지표의 이름·label·unit·plotId·정의 내용은 전부 보존한다. 정확히 같은 정의 문자열만 공통화하고, 비슷해 보이는 다른 연산은 합치지 않는다. `peakToPeak`의 “최대−최소”와 `halfPeakToPeak`의 “그 절반”, 극값 자체와 극값 위치를 구분한다. 누락된 정의·순환 참조·알 수 없는 참조는 전송 전에 거부한다.

**후보 2: 계획에 이미 있는 실행 입력의 중복 표기를 줄인다.**

원본 `plan.steps`에 `inputs`·`depends_on`·`required_prior_outputs`·`run_if`가 있는데 `execution_view`에도 반복된다. 원본 계획은 그대로 두고, 전송용 `execution_view`에서 그 복사본만 제거하는 후보를 검토한다.

```json
{
  "step": "compare", "kind": "tool", "action": "compare_runs",
  "computed_outputs": {
    "pressure": {"label": "압력", "unit": "mTorr", "plotId": null, "definition": "저장된 실험 수치"}
  }
}
```

이 예시에서도 실제 입력·의존성·실행 조건은 원본 `plan.steps`에서 모두 읽을 수 있어야 한다. `computed_outputs`는 암묵 계산 설명이므로 남긴다. `program_effects`의 “모든 후보”, “사용자가 고른 Run 전체”, “미래 결과 참조”와 같은 설명도 남긴다. d1이 복사본에 의존했다면 이 후보는 폐기한다.

**후보 3: 모델이 해석하지 않는 추적용 hash를 전송에서만 생략한다.**

`plan_digest`·`input_digest`는 약 73토큰이다. 검토 원본과 저장·결과 매칭에는 그대로 두되 d1 전송 상태에서만 뺀다. `schema_version`·`plan_revision`·`prompt_version`까지 일괄 삭제하지 않는다. hash만 빼는 변경은 절감량이 작으므로 단독 대폭 개선안으로 보지 않는다.

다음 내용은 첫 후보에서 **줄이지 않는다**.

- 전체 도구 종류·핵심 역할·입출력 계약·바인딩 scope: 계획에 없는 도구도 잘못된 도구 추가를 발견하는 데 필요하다.
- 단위·배율·AND 필터·양끝 포함 범위·정렬 방향·후보 전체·직접 선택·기준 Run·경향 축·미래 참조 규칙.
- 질문·계획·`source.quote`·이력·확정 문맥, `check_specs`, 각 검사 지침·선택지.
- null과 0, 빈 배열과 생략의 구분. 공통 JSON은 이미 공백을 줄여 직렬화하므로 공백 제거를 성과로 계산하지 않는다.

### Decision gates

1. 구현 첫 단계는 CPU 전용 조사다. 후보별 필드·문장·참조의 보존표와 실제 엔진 tokenizer 기준 전체 packed 토큰을 기록한다. 먼저 후보 1+3을 보고, 부족할 때만 후보 2를 추가한 표현을 조사한다.
2. 각 인공 입력에서 `1 − compact의 전체 검사 합산 토큰 / full의 전체 검사 합산 토큰`을 계산하고, **35입력의 절감률 중앙값이 10% 미만**이면 대폭 개선 후보로 보기 어렵다고 보고하며 실제 모델 대조를 시작하지 않는다. 10%는 채택된 기술 성능이 아니라 이 계획의 제안 관문이다. 보존 정보가 빠지거나 특정 입력이 더 길어지거나 기존 한도를 넘겨도 중단한다.
3. 관문을 통과한 표현 하나만 `compact-v1`으로 동결한다. 모델 결과를 보고 정의·지침을 계속 고쳐 같은 평가를 재실행하지 않는다. 본 대조에는 full과 동결 compact 두 조건만 둔다.
4. 새 정확도 회귀가 생기거나 시간 목표를 못 채우면 자동 적용하지 않는다. 효과가 작다는 결론도 이 계획의 유효한 결과다.

### Integration boundary

원본 `build_plan_review_context()`는 바꾸지 않는다. 별도 순수 함수 `project_plan_review_input(context, mode)`를 로컬 전용 `core/review_input.py`에 두는 것을 제안한다. `full`은 원본 표현, `compact`는 위에서 동결한 표현이다. 입력을 mutate하지 않으며 도구 계약 값은 기존 `tool_contracts`를 데이터 원본으로 삼는다.

연결은 `V2LocalLLMModelGateway.review_plan()`에 한정한다. 전송용 view를 한 번 만들고, **동일 view + 원본에서 만든 `review_questions()`**를 token guard와 실제 POST에 전달한다. module-level `review_plan()`의 직접 호출 경로도 같은 함수를 사용하되 중복 축약하지 않는다. 파싱·`rejection_evidence()`·`matches_review_context()`·피드백은 항상 **원본 context**를 사용한다.

공용 `native_request()`나 `review_answer()` 전체에 축약을 넣지 않는다. 추적에는 원본 digest와 별도의 전송 입력 hash·표현 버전·토큰 수를 남기고 기존 최종 응답 스키마에는 새 필드를 넣지 않는다. snapshot을 다시 쓰거나 과거 판단을 새 표현으로 치환하지 않는다.

설정은 `AGENT_V2_LOCAL_LLM_D1_REVIEW_INPUT_MODE=full|compact` 하나로 제한하고 기본값은 `full`이다. 표현 버전·projection 소스 hash·도구 계약 hash는 `Settings.versions()`의 fingerprint와 `runtime_profile()`에 연결한다. 과거 full 준비 증거를 compact 준비 완료로 인정하지 않는다. 표현 버전은 기존 의미 검토 `PROMPT_VERSION`과 분리한다. 의미 지침이 바뀌지 않았다는 뜻이지 전송 입력이 같다는 뜻은 아니다.

### Structural alternatives if compaction is weak or risky

| 대안 | 유지되는 것 / 바뀌는 것 | 권고 |
|---|---|---|
| 같은 입력의 GPU 커널·연산 구현 최적화 | 원본 토큰·독립 검사·attention mask·readout·calibration을 보존하고 계산 구현만 개선 | **정확도 위험을 더 늘리고 싶지 않을 때의 우선 조사 방향**. 커널별 계측부터 필요하며 속도 개선은 미확인 |
| 검사별 전용 입력 구성 | 전체 원본은 보관하지만 필터 검사는 해당 조건과 의존성, 작업 누락 검사는 전체 계획 등으로 입력을 나눔 | 계산량을 더 줄일 가능성. 전역 맥락·교차 단계 오류를 놓칠 위험이 있어 별도 설계/정답 대조 필요 |
| 공통 본문 한 번 + 여러 검사를 한 입력에서 계산 | 검사 ID는 같아도 질문끼리 본문 상태에 미치는 영향이 달라짐 | 과거 공동 입력은 B 4/8→C 2/8로 회귀. 이 계획의 자동 대안으로 채택하지 않음 |

첫 대안은 “병렬 4개”를 다시 늘리는 방식과 다르다. 예를 들어 현재 attention의 점수 행렬 생성·chunk 반복·동기화 중 실제로 시간이 큰 부분을 확인한 뒤, **동일 마스크를 표현할 수 있을 때만** 더 효율적인 커널을 검토한다. MLX에는 mask를 받는 최적화 attention API가 있지만 d1의 혼합 full/sliding attention·질문 분리와 동일한 계산을 지원하는지는 확인되지 않았다. 부동소수점 계산 순서가 바뀔 수도 있으므로 결과 동등성 검증이 필요하다. 현재 기본 Q8의 llama.cpp와 실험 MLX는 각각 프로파일링해야 하며, MLX 함수를 바꾸는 것을 Q8 최적화로 표현하지 않는다.

두 번째 대안은 검사 개수·출력 계약은 유지할 수 있지만 **검토에 주는 맥락은 바뀐다**. 단순한 손실 없는 축약이라고 부르지 않는다. 질문·정책과 관련 단계의 선행/후행 의존성, 확정 문맥의 닫힌 연결을 보존하는 별도 설계가 필요하며, 여기서는 구현하지 않는다.

지시서 공통 부분을 일반 LLM의 KV 캐시처럼 재사용하는 것도 현재 d1의 간단한 해법이 아니다. pin된 d1 MLX 구현은 full-attention에서 본문 상태가 그때의 질문들을 읽으므로 질문 집합·순서에 의존하며, 세트/요청 간 상태를 캐시하지 않는다고 명시한다. 본문만 먼저 계산하도록 attention을 바꾸면 같은 모델·같은 검토라는 보장이 깨진다.

**축약 관문을 못 넘으면:** 이 문서에 절감 가능한 양과 위험을 기록하고 full을 유지한다. 우선 동일 입력의 커널 병목 조사 계획을 별도로 제안한다. 이후에도 개선 여지가 작고 더 큰 단축이 필요하면 검사별 맥락 설계를 논의한다. 모델 교체·양자화 강화·검사 생략을 몰래 섞지 않는다.

## Implementation Units

### U1. Static inventory and frozen candidate

**요구사항:** R1·R2·R7. **파일:** 기존 `core/plan_review.py`, `core/plan_checks.py`, `comparison_catalog.py`는 조사 원본으로 읽기만 한다. 결과는 Git 제외 `.local/runtime/d1-review-input/`의 보존표·토큰 표에 기록한다. 이 단계는 제품 코드 변경 없이 끝낼 수 있다.

- [ ] 기존 정상/오류 계획 14쌍, 기존 인공 `good_lookup`·`bad_missing_compare`·`bad_extra_explanation` 3건, 아래 정의 구분 전용 2쌍(4건), 총 35입력에 대해 full 입력을 동결한다. 기존 8종 probe 전체가 이 집합에 포함되는지는 context digest로 확인한다. 이것은 토큰 조사이며 추론·정확도 평가가 아니다.
- [ ] 모든 32지표 정의·단위·label·plotId가 후보에서 복원되는지, view에서 뺀 복사본이 원본 계획의 정확한 경로에 존재하는지 확인한다. 후보 1/2/3 각각의 비용과 순절감량을 표시한다.
- [ ] 전체 state뿐 아니라 검사별 지침·선택지·템플릿을 포함한 토큰, 한 검사 최대 토큰, 모든 검사 합산 토큰을 센다. 검사 수 감소를 절감으로 계산하지 않는다. Q8 tokenizer가 기준이며 MLX 숫자와 섞지 않는다.
- [ ] 10% 관문과 정보 보존을 통과하면 가장 작은 후보 하나를 동결한다. 못 넘으면 U2~U4를 실행하지 않고 구조 대안을 보고한다.

### U2. Plan-only projection and provenance

**요구사항:** R1~R4·R6. **예정 파일:** `core/review_input.py` 신설, `core/model_gateway.py`, `config.py`, `runtime.py`, `intentional-differences.json`, `.env.local-llm.example`, `docs/development/agent-v2-local-llm.md`의 필요한 부분만 변경한다. 이 목록은 `agent/python/src/kplasma_agent/v2_local_llm/` 아래 파일을 뜻한다(예시 env·문서 제외).

**검증 파일:** 새 `agent/python/tests/v2_local_llm/test_review_input.py`; 기존 `test_model_gateway.py`, `test_decisions.py`, `test_native_token_counting.py`, `test_config.py`, `test_readiness.py`, `test_condition_review.py`, `test_plan_review.py`, `test_plan_review_graph.py`, `test_clone_boundary.py`.

- [ ] 먼저 원본 불변·full 경로 호환·32지표 복원·누락/알 수 없는 참조 거부·후보 2의 입력/의존성 보존을 고정하는 작은 테스트를 작성한 뒤 projection을 구현한다.
- [ ] MockTransport로 계수 입력과 실제 POST의 state·질문·지침·선택지가 일치함을 검사한다. module-level 직접 호출, 재시도 없는 오류·timeout·UNAVAILABLE, 미지 mode, 빈/누락 context, 같은 view 재입력도 다룬다. compact는 유효한 원본 context에서만 만들고 알 수 없는 표현을 full로 조용히 우회하지 않는다.
- [ ] 답변 검토·계획 도구 스키마·최종 payload·stream·피드백 근거가 기존과 같음을 확인한다. projection 실패로 d1을 건너뛰거나 PASS를 만들어내지 않는다.
- [ ] mode/표현 hash가 다르면 준비 보고서·재개 identity를 재사용하지 못하도록 검사한다. 새 helper는 clone 경계의 `newFile`로 등록하고 필요한 selector만 좁게 허용한다. frozen clone baseline·outputs·초기 manifest를 바꾸지 않는다.

### U3. Memory preparation and bounded paired comparison

**요구사항:** R2·R4~R7. **예정 파일:** `agent/python/evals/local_llm_d1_review_input_probe.py`와 그 집계 테스트 `agent/python/tests/v2_local_llm/test_d1_review_input_probe.py`를 추가하고 기존 probe의 인공 입력·파서·메모리 감시를 재사용한다. 정의 구분용 인공 계획은 새 `agent/python/tests/v2_local_llm/review_input_cases.py`에 두고 원래 14쌍 fixture를 바꾸지 않는다. 실제 대조는 제품의 `gateway.review_plan(original_context)` 경로를 사용하며 평가 전용 축약/전송 경로를 따로 만들지 않는다. 필요한 native 요청·응답 및 단계별 계측은 로컬 HTTP 관측으로 수집하고 제품 반환 계약에 넣지 않는다. 기존 A/B/C/D 평가 의미는 변경하지 않는다. 필요하면 `agent/python/evals/local_llm_measure.py`의 새 표현 증거 연결만 확장하고 `test_measure_preparation.py`에서 검사한다.

**주비교:** 현재 기본 **llama.cpp Q8 개별**의 full 대 compact다. 가중치 revision·정밀도·tokenizer·calibration·batch/ubatch·timeout은 동일하다. MLX BF16나 독립4를 새로 켜지 않는다. 실행 시 기본 엔진이 달라져 있으면 임의로 Q8로 바꾸지 말고 차이를 보고한 뒤 비교 계획을 정정한다.

- [ ] 모델 호출 전 설정과 실제 평가 그래프의 `plan_review_enabled=true`, 실제 서버 인자·프로필·Docker 1536MiB·메모리 정책·원래 Qwen 캐시 OFF를 확인한다. 토큰 집계에서 절감이 확인됐다는 이유로 새 프로필을 ready 처리하지 않는다. 실험 사전 검사는 `verify_artifacts`·`live_facts`·메모리 증거·그래프 상태로 수행하고, 추론을 포함하는 `Settings.readiness()` 반복 호출을 숨은 워밍업으로 사용하지 않는다.
- [ ] 공유 스택의 DB·데이터를 보존하고 full/compact 각각 기존 인공 메모리 7종을 한 세트씩 실행한다. Qwen↔d1 교대·입력 한도·모델 해제를 확인하고 mode가 일치하는 새 준비 증거를 만든다. 일반 단위 검사 입력의 통과와 실제 계획 context의 축약 검증을 구분한다.
- [ ] U1에서 동결한 35개 context를 사용한다. 각 계획에 예상 상태, 오류 계획의 기대 검사 ID·오류 종류·근거 경로를 **실행 전에** 작성한다. 모델 출력을 정답으로 사용하지 않고 이 oracle을 d1에 보내지 않는다.
- [ ] 정의 구분 전용 D01은 인공 질문이 요구한 `current.peakToPeak`를 오류 계획에서 `current.halfPeakToPeak`로, D02는 요청한 `ied.peakEnergy`를 `ied.maximum`으로 바꾼 정상/오류 쌍이다. 대상·검색 조건·선행 단계는 같게 고정한다. 기대 오류는 `outputs.<비교 step ID>`의 누락/불필요한 출력과 해당 `inputs.fields` 경로이며, 출력 지표를 검색 필터 오류로 지적한 결과는 이유 정답으로 세지 않는다. 기존 P02 오류는 검색 범위 변경이므로 이 검증을 대신하지 못한다.
- [ ] 먼저 기존 `review_cases()`의 8종 전체를 full/compact 각각 1회: **16개 검토 요청**. 정상 조회·비교·선택, 경계·단위 오류, 비교 누락, 요청하지 않은 설명 추가, 필요한 선택 생략에서 새 회귀가 있으면 확대·반복하지 않는다. 원래 놓치던 오류가 그대로 남은 것도 기록한다.
- [ ] 관문 통과 시 나머지 27입력 × 2조건 = **54개**를 실행한다. 각 입력은 같은 snapshot을 사용하고 조건 순서를 full→compact/compact→full로 교대한다. Qwen으로 계획을 재생성하지 않는다.
- [ ] 품질 관문을 통과하면 P01 정상(의존성), P02 정상(지표 정의), P09 정상(선택 연결)의 양 조건을 추가 2회씩 실행한다: **12개**. 이 세 사례는 각각 총 3회가 된다. 반복별 조건 순서도 교대한다.
- [ ] 계수·직렬화·HTTP 전체 시간, 지원되는 모델 load/forward/release 시간, 실제 토큰 수·pressure·swap·RSS·DB OOM·모델 해제를 기록한다. Q8가 단계별 시간을 노출하지 않으면 ‘미분리’로 보고하며 전체 시간을 순수 GPU 시간으로 표기하지 않는다. GPU 센서는 같은 도구·주기일 때 보조 지표로만 비교한다.
- [ ] 실패·누락·UNAVAILABLE·critical을 실패 그대로 기록한다. 자동 재실행·추가 워밍업·유료 호출·40문항 웹/API 재평가·다른 앱 종료는 하지 않는다. 최근 환경에는 warning 9표본과 swap 약 347MiB 증가 기록이 있으므로 과거 무경고 수치를 현재 측정으로 복사하지 않는다.

**실행 상한:** 본 d1 대조 최대 **82개 검토 HTTP 요청**(16+54+12). 메모리 7종×2는 별도 **14추론 요청**(Qwen 8, d1 6)이며 비교 점수에 합치지 않는다. 최종 워커 복구에 실제 계약 준비 확인이 필요하면 **한 세트 최대 4요청**(Qwen 3, d1 1)만 별도 허용한다. 합계 최대 **100추론 HTTP 요청**이고, 내부 검사 연산 횟수와 tokenizer/count 요청 수는 따로 보고한다. 관문 실패 시 남은 횟수를 사용하지 않는다. 이 수량은 향후 구현 승인을 받았을 때의 상한이며 이번 계획 작성에서 실행하지 않는다.

### U4. Decision report and safe return

**요구사항:** R3·R5~R7. **산출물:** 향후 `docs/verification/2026-11-15-local-llm-d1-review-input.md`에 집계만 기록한다(실제 실행일에 맞춰 날짜 변경). 원시 입력·응답·메모리·DB hash·세션은 Git 제외 `.local/runtime/d1-review-input/`에 보관한다.

- [ ] 아래 판정표로 새 회귀·기존 오답·수정된 오답·확률 변화·성능을 각각 보고한다. 상태만 맞고 지적 이유가 틀리면 이유 정답으로 세지 않는다.
- [ ] 채택 조건을 통과해도 기본값 full을 유지하고 실제 웹 검증/승격은 별도 결정한다. 본 비교는 전체 Agent 정확도를 입증하지 않는다.
- [ ] 소유 실험 서비스만 정리하고 원래 Qwen/d1/워커 설정과 Docker 1536MiB를 복원한다. full 프로필의 유효한 준비 증거를 확인하고 DB Run·버전·대화 snapshot·요청 수 보존을 비교한다. 정리/재개 실패를 성공으로 숨기지 않는다.
- [ ] 축약 이득이 작거나 정확도가 떨어지면 원인과 보존하지 못한 판단 맥락을 적고, 위 구조 대안 중 동일 입력 커널 조사부터 별도 제안한다. 그 대안 구현·새 엔진 설치·새 모델 다운로드는 시작하지 않는다.

## Verification Contract

| 판정 | 통과 조건 / 보고 방식 |
|---|---|
| 내용 보존 | 32지표의 정의·unit·label·plotId와 계획 입력·의존 조건을 원본 정보로 정확히 복원 가능. 코드상의 복원 가능성과 모델 정확도 동등성은 구분 |
| 검사·계약 보존 | 모든 입력에서 검사 ID·개수·순서·지침·선택지 동일, 원본 digest·snapshot·근거 경로 보존, 계수/POST view 동일 |
| 정확도 | full에서 맞힌 사례·검사·이유를 compact가 새로 틀리지 않음. 오류 계획의 신규 PASS와 정상 계획의 신규 ISSUE/UNCLEAR를 각각 실패로 기록. 기존 오답을 고친 차이는 독립 oracle로 확인하고 별도 보고 |
| 반복 안정성 | 3회 반복한 세 사례에서 신규 판정 흔들림 없음. 확률이 바뀌면 차이를 보고하되 확률 숫자의 완전 일치 자체를 의미 정확도 조건으로 강요하지 않음 |
| 속도 | 대표 3사례 각각의 3회 전체 시간 중앙값을 먼저 산출하고 그 3값의 중앙값으로 full/compact 비교. 목표 20% 이상 단축, 어느 대표 사례든 10% 초과 악화 시 채택 보류. 첫 회 35입력 시간도 전부 공개 집계. 표본이 작아 보편 성능·통계적 유의성을 주장하지 않음 |
| 메모리 | development warning은 기록·허용, critical/미지 상태 즉시 중단, DB OOM/kill 0, 모델 해제·전환 성공. 시작 swap과 증가·단계별 피크를 보고하고 준비 통과를 무스왑 안정성으로 표현하지 않음 |
| 실패 처리 | 누락/추가/중복 검사, 잘못된 확률·선택지, timeout·projection 오류·토큰 초과를 기존 오류 규칙으로 처리. 검사 생략·가짜 PASS·숨은 상용 fallback 없음 |
| 보호 파일 | graph·`core/plan_checks.py`·`core/plan_review.py`·계획/최종 응답 스키마·v2/v3 소스의 시작/종료 hash 동일. 새 helper와 gateway/config/runtime의 의도한 변경만 허용 |

예정된 코드 검증은 `agent/python`에서 수행한다. 새 projection·probe 집계 테스트와 위 U2 영향 테스트를 먼저 실행하고, 로컬 namespace 테스트 전체·영향 파일 Ruff/mypy·기존 공통 응답 계약 검사를 이어서 수행한다. 기존 `test_clone_boundary.py`와 원본 출력 비교의 예외는 baseline을 고쳐 없애지 않고 기존 예외/신규 실패를 구분한다. 실제 모델을 호출하지 않는 테스트와 실제 검토 요청을 별도 표에 기록한다.

**검토 방식의 구분:** 고정 계획 비교는 최초 계획의 검토 판정만 측정하므로 재계획을 실행하지 않는다. 실제 그래프의 재계획·답변 검토 예산은 그대로 유지한다. 후속 웹 검증이 승인된다면 최초 통과, Decisions 지적, REPLAN 후 최종 통과/실패를 분리하고 이번 d1 단독 점수와 합치지 않는다.

## Definition of Done

- [ ] 실제 절감량·보존표·새 정확도 회귀·검사 이유·시간·메모리를 근거로 compact를 계속 검토할지 또는 중단할지 결정할 수 있다.
- [ ] 충분히 줄일 수 없을 경우 U1만으로 중단할 수 있고, 그 경우도 ‘정적 조사 완료·추론 미실행·구조 대안 제안’으로 정직하게 보고한다.
- [ ] 그래프·검사·최종 응답·저장 데이터와 원래 실행 환경을 보존했다는 증거가 있다. 기본값 승격·웹 전체 평가·commit/push는 별도 지시 전 수행하지 않는다.

## Sources

- 사용자 지시: 계획만 작성, 도구 설명·중복 정보 축약 예시, 기존 검사·그래프·응답 보존, 정확도·시간 비교, 축약 한계와 구조 대안 제시.
- `agent/python/src/kplasma_agent/v2_local_llm/core/plan_review.py`, `core/plan_checks.py`, `core/model_gateway.py`, `core/budget.py`, `comparison_catalog.py`.
- `agent/python/tests/v2_local_llm/plan_review_cases.py`: 정상/오류 14쌍. `agent/python/evals/local_llm_d1_joint_probe.py`: 별도 기존 8종·인공 조회 입력·기존 파서/메모리 도구.
- [독립4 계획](2026-11-15-001-local-llm-d1-independent-batch4.md), [독립4 결과](../verification/2026-11-15-local-llm-d1-independent-batch4.md), [공동 입력 결과](../verification/2026-11-14-local-llm-v2.3-qwen-d1-joint.md), [기존 상용 v2 평가](../verification/2026-11-11-agent-v2-round3.md).
- 로컬 GPU 진단 집계: `.local/runtime/d1-gpu-profile/report.md`, `summary.json`. 원시 자료는 비공개 보관하며 공개 문서로 복사하지 않는다.
- pin된 엔진 코드: `.local/runtime/v2.3-qwen-d1-joint/mlx-decision-source/src/mlx_decision/models/d1lfm3/model.py`와 `backbones/qwen3_5/base.py`. 구조 대안 조사 시 해당 pin을 기준으로 삼고 main 최신판의 기능을 현재 기능으로 가정하지 않는다.
- [MLX 0.32.4 최적화 attention API](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.fast.scaled_dot_product_attention.html): mask 지원 자체만 확인한 근거이며, 현재 d1과의 동등성·속도는 미검증이다.

계획 자체 검토에서 원본/전송 표현 분리, count/send 일치, 정의 참조의 의미 손상, 기존 오답과 신규 회귀의 구분, 모델 호출 상한, 효과 부족 시 중단 경로를 점검했다. 지표 정의를 잘못 이해하는 오류 사례가 빠진 점을 보완해 전용 2쌍을 추가했고, 기존 비교 누락·설명 추가 오판도 대조 집합에 포함했다. 원래 14쌍을 고쳐 이 검사를 대신하지 않는다. **이번 작성 단계에서는 구현·제품 테스트·모델 추론·Docker/서비스 변경을 실행하지 않았다.**

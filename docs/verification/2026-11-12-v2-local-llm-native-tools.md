# v2_localLLM의 submit_plan 도구 호출 복구

2026-11-12 사용자 요청에 따라 계획 수신을 본문 JSON 방식에서 실제 `submit_plan` 도구 호출로 변경했다.
Qwen3.5-9B MLX 4bit·d1-2B Q8_0, M4 Pro 24GiB, loopback 인증과 16K 입력 상한을 유지한다.
실제 모델 시험은 모두 인공 문자열·인공 Run으로 수행한다. 원시 응답·모델 키·연결 파일은 Git 밖에 보관한다.

## 원인 분리

- 기존 v2의 `tool_choice={type:function,name:submit_plan}` 요청을 LM Studio 0.4.28+2가 HTTP 400으로 거부했다.
  오류는 `Expected 'none' | 'auto' | 'required', received object`였다.
- Chat Completions의 이름 지정 객체도 HTTP 400 (`Invalid tool_choice type: 'object'`)이었다.
- `required`와 단 하나의 `submit_plan`을 등록하면 정식 도구 호출을 반환한다.
- 같은 고정 계획의 원시 생성에서도 `<parameter=base_revision>None</parameter>`가 나왔다.
  API의 인자에는 `"None"` 문자열이 들어가 기존 nullable 정수 검증에서 거부됐다.
- Responses 경로에서는 같은 계획에 대해 3개 도구 호출과 누적 입력 20106 tokens가 반환됐다.
  `strict=false`와 동등한 nullable schema 표현 변경으로도 해결되지 않아 채택하지 않았다.
- Chat Completions의 native 경로는 도구 호출 1개·입력 6446 tokens를 반환했다.
  따라서 현재 Chat Completions 주소에서 도구 호출 모드를 사용한다. 본문 JSON 출력 모드는 planner에 사용하지 않는다.

## 현재 요청과 검증

`tools`에는 보존한 `submit_plan` 정의 하나만 전달한다. 함수 이름·설명·인자 schema는 원래 v2의 계약을 유지한다.
`tool_choice=required`와 `parallel_tool_calls=false`를 사용하고, 응답에서도 다음을 확인한다.

1. 답변 후보가 하나이며 `finish_reason=tool_calls`일 것.
2. native function call이 정확히 하나이며 이름은 `submit_plan`, 호출 ID는 비어 있지 않은 문자열일 것.
3. `function.arguments`가 JSON 문자열일 것. 일반 `content` JSON을 대신 읽지 않는다.
4. 아래의 좁은 형식 변환 후 기존 strict `PlanDraft`와 그래프 검증을 통과할 것.

형식 변환은 다음 범위뿐이다.

| 대상 | 허용한 변환 | 거부하거나 유지하는 것 |
|---|---|---|
| `base_revision` | `"None"`/`"null"` → null, 정규 양의 정수 문자열 → 정수 | bool, 0, 음수, `"01"`, 소수·임의 문자열은 거부 |
| `steps`, `requirements` | 유효한 JSON 문자열에 담긴 목록을 한 번 decode | 깨진 JSON·목록이 아닌 객체/문자열은 거부 |
| 사용자 조건·인용·단위 등 | 변환 없음 | 값 보정·조건 추가·단계 생성·허용되지 않은 필드 삭제 없음 |

nullable `message`/`function`, 잘못된 호출 ID·인자 자료형 등은 `MODEL_OUTPUT_INVALID`로 처리한다.
실제 native 호출을 기존 실패 기록의 `function_call` 형태로 매핑해 재계획에 원래 인자와 실제 usage를 전달한다.
도구 호출·계획 생성·재계획 각각 모델 API 호출은 한 번이며 SDK 자동 재시도와 본문 JSON fallback은 없다.

실제 인공 검색 질문에서 `requires`에 조건 연산자를 넣거나 `tool` 단계에 `confirmation`을 붙이는 오류도 확인했다.
기존에는 gateway의 strict 검증 실패가 오류 코드와 인자 끝 500자로만 재계획에 전달됐다.
잘못된 필드가 앞부분에 있으면 오류 위치가 사라졌다. 이제 strict 검증의 경로·이유·종류를
`generation_failure.validation_error`에 함께 전달한다. 원래 native 인자와 usage는 그대로 보존한다.
JSON 파싱 오류도 `/steps`·`/requirements`·루트 중 실제 위치를 전달하며 자동 수리하지 않는다.
이 변경은 오류 보고 보조 함수에만 한정한다. 그래프 노드·간선·분기·검증 규칙·실행 횟수는 바꾸지 않았다.

인공 브라우저 검증 중 요청 종료 뒤 `LOCAL_MEMORY_PRESSURE`로 worker가 종료되는 별도 문제도 확인했다.
소유한 Qwen은 요청 종료 후 모델 lease를 가진 상태에서 해제한다. 대기 중 메모리 경고는 새 요청을 claim하지 않고
정상 압력이 돌아오기를 기다린다. 초기 준비 실패와 다른 환경·계약 불일치는 계속 차단하고,
CLI 오류에는 준비 실패 코드를 함께 표시한다. 메모리 검사를 우회하거나 경고를 정상으로 바꾸지 않는다.

## 유지한 계약

그래프 노드·분기·의미 검토·최대 2회 재계획·사용자 선택·계산 코드·최종 답변 schema는 변경하지 않았다.
writer의 JSON Schema·스트리밍 projector와 d1 native 의미 검토도 유지한다.
`planProtocol=native-submit-plan-chat-v1`과 구현 hash로 예전 JSON 경로의 checkpoint/PASS를 재사용하지 못하게 한다.
기존 v2·v3 구현은 이 수정의 대상이 아니다.

## 검증

```sh
cd agent/python
.venv/bin/python -m pytest -c pytest-v2-local-llm.ini -q
.venv/bin/python -m mypy src/kplasma_agent/v2_local_llm/model_client.py src/kplasma_agent/v2_local_llm/core/model_gateway.py src/kplasma_agent/v2_local_llm/runtime.py src/kplasma_agent/v2_local_llm/worker.py src/kplasma_agent/v2_local_llm/graph.py evals/local_llm_smoke.py
```

- 최종 실제 native smoke: plan·writer JSON·SSE·d1 통과, 36.055초. plan은 서버 usage 기준 입력 6445·출력 210 tokens였다.
- native 호출/인자 복구/부정 입력 검사는 기존 JSON 경로 및 잘못된 응답 구조에서 실패하는 것을 먼저 확인한 뒤 수정했다.
- Python: 349 passed, 초기 복제 시점 전용 검사 8 deselected. 동결 AST·지침·도구/답변 schema·namespace 검증 포함.
- 지정 mypy 6개 파일 통과. 원래 오류를 정상 계획으로 꾸미는 복구는 도입하지 않았다.
- 잘못된 인자의 경로가 없어서 실패하는 회귀 검사를 먼저 확인했다. 형식 실패 → 기존 재계획 → 의미 검토 → 답변의 순서도 검사했다.
- 일시적 메모리 경고 때 claim 없이 기다리는 검사와, 요청 종료 후 lease를 유지한 채 Qwen을 해제하는 검사를 실패 상태부터 확인했다.
- 오류 위치 보강 전 실제 브라우저 4개 질문은 최초 성공 0/4, 재계획 후 최종 성공 1/4였다.
  개념 설명만 완료했고, 검색·혼합 질문·선택 후 중첩 검색은 인자/계획 검증에 실패했다. 모두 인공 Run이었다.
- `temperature=0`과 형식 지침 추가 시험은 각각 인공 검색 질문 두 개에서 유효한 계획을 만들지 못해 채택하지 않았다.
- 브라우저 검사의 활동 기록은 실제 request API의 `progress.activities`에서 읽도록 수정했다.
  화면의 결과와 후보·d1 검토·Run 선택을 각각 검사하며 완료 상태만으로 성공 점수를 주지 않는다.

이전 JSON 경로의 12/24 점수와 이번 도구 호출 경로의 결과는 구분한다. 연결·형식 검증만으로 분석 정확도가 기존 v2와 같다고 판단하지 않는다.

## 오류 위치 전달 보강 후 실제 브라우저 결과

```sh
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
KPLASMA_VERIFY_ENV_FILE=.local/runtime/full-stack/local.env \
node scripts/agent/verify-v2.mjs --live --graph-version v2_localLLM
```

새 인공 DB·백엔드·브라우저에서 같은 네 질문을 끝까지 실행했다. d1 의미 검토는 켠 상태였다.
기존 사용자 서버와 실험 데이터에는 접근하지 않았다. 아래 성공은 API의 `COMPLETED`가 아니라
기존 계획·계산·질문 충족 검사와 `answerSnapshot.executionStatus=COMPLETE`를 기준으로 한다.

| 질문 | 재계획 | 최종 실행 상태 | 활동 시간 | 최종 응답 schema |
|---|---:|---|---:|---|
| IED 개념 설명 | 1 | COMPLETE | 78.762초 | 통과 |
| 이온 플럭스 40 초과 검색 | 2 | FAILED | 78.102초 | 통과 |
| 검색과 개념 설명 혼합 | 2 | FAILED | 85.609초 | 통과 |
| 두 Run을 사용자가 선택하는 중첩 검색 | 2 | FAILED, 선택 단계에 도달하지 못함 | 98.360초 | 통과 |

- 최초 성공 0/4, 재계획을 포함한 최종 성공 1/4로, 오류 위치 전달 보강 전과 같은 성공 수였다.
- 실제 11개 계획 생성 시도 중 gateway 생성 오류 8개는 모두 native `submit_plan` 1개와 인자 검증 오류를 보존했다.
  오류를 재계획 입력에 전달했지만 모델이 잘못된 필드와 깨진 JSON을 모두 고치지는 못했다.
- 4개 최종 응답은 기존 `GraphV2LocalLLMAnswerSnapshotV1`의 strict 검증을 통과했다.
  세 실패 질문은 계산 도구를 호출하지 않았고 성공이나 임의 후보를 만들지 않았다.
- 390 / 800 / 1008 / 1440px 화면 16개를 보관했고 가로 넘침 검사는 실패하지 않았다.
  브라우저 기록의 11건은 대화 전환 시 `/workspace`·이벤트 요청의 `ERR_ABORTED`였다.
- 수정 후 worker는 메모리 경고로 종료되지 않고 네 질문을 처리했다. 소유한 검증 worker·서버·DB는 도구가 정리했다.
- Playwright는 질문 충족 검사가 실패해 exit 1이었다. Python 349개·지정 mypy 6개·Ruff·TypeScript typecheck·ESLint와
  고정 입력 native 연결 smoke가 통과했다는 사실과 구분한다.

원시 응답·모델 기록·화면·인증 연결 파일은 저장소 밖의 로컬 검증 디렉터리에만 보관했다.
이번 수정은 native 도구 호출과 오류 처리 복구이며, 현재 모델 조합의 검색 계획 생성 안정화는 미완료다.
실데이터 사용 준비 완료나 기존 v2와 동등한 정확도를 주장하지 않는다. v3 실제 모델 검증은 수행하지 않았다.

# v2_localLLM llama.cpp 전환·계획 생각 모드·웹 5문항 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 작성 시점의 계획이며 이후 실제 상태는 아래 실행 현황과 검증 기록을 따른다.

**2026-11-13 최신 실행 현황:** 준비 안정화 수정 후 사용자의 지정에 따라 Docker VM3GiB를 적용했다. DB 검사·새 전체 스택 인공7행 검사를 통과하고 Q01~Q05 웹 자동5/5·자동 UI5/5, API0을 완료했다. 최초 계획 즉시 채택2/5·재계획 합계3회, 추가 swap0·관측 critical0이지만 웹673표본 중 warning174개와 Q03 답변 안내 한계는 남는다. [최신 검증·피크 기록](../verification/2026-11-13-v2-local-llm-docker-3gib.md). 준비 안정화 수정 자체는 [이전 기록](../verification/2026-11-13-v2-local-llm-stable-web5.md)을 따른다. 전체40문항·상용v2 동등성 검증 완료를 뜻하지 않는다.

**후속 사용자 지시 반영:** Qwen context만 24,576으로 변경하고 d1 검토 ON 상태로 메모리를 재검사했다. warning·추가 swap 160.93MiB로 실패하여 조건부 웹 Q01~Q05는 접수하지 않았다. 기존 16K 입력·6K 계획 출력·그래프·응답 계약·통과 기준은 유지한다. 아래 32K는 최초 출발 프로필의 기록이며 현재 값은 [24K 재검사 기록](../verification/2026-11-13-v2-local-llm-24k-memory.md)을 따른다.

**추가 사용자 지시 반영:** 24K를 유지하고 Qwen batch/ubatch만 256/256으로 변경했다. 추가 swap 0이지만 warning으로 메모리 검사가 실패해 웹 접수는 0이다. d1 설정·검토 ON과 기존 그래프·응답 계약을 유지했다. [256 검사 기록](../verification/2026-11-13-v2-local-llm-24k-batch256-memory.md).

**Goal:** 독립 `v2_localLLM`의 Qwen 실행을 llama.cpp로 전환하고 계획 생각 모드를 적용한 뒤, 기존 40문항 중 첫 5문항만 웹에서 평가한다.

**Architecture:** 그래프·도구·계획 필드·최종 응답 계약은 유지하고 Qwen 실행 및 전송 경계만 교체한다. Qwen과 d1은 별도 llama-server 프로세스를 사용하며 24GB 맥에서 한 모델씩 메모리에 상주시킨다. 계획·재계획은 생각 모드 ON, 답변 작성·재작성은 OFF로 시작한다.

**Tech Stack:** 기존 Python/OpenAI 호환 client·LangGraph·httpx, llama.cpp b12317/Metal, Qwen3.5-9B GGUF Q4_K_M, 기존 d1-2B Q8_0, 기존 Playwright 웹 평가기.

**Spec:** [독립 그래프 원계획](2026-11-12-001-feat-v2-local-llm-plan.md), [현재 실행 계약](../development/agent-v2-local-llm.md), [40문항 기준 결과](../verification/2026-11-13-v2-local-llm-baseline-40.md), [형식 오류 원인 조사](../verification/2026-11-13-v2-local-llm-argument-origin.md), 사용자의 2026-11-13 전환·생각 모드·첫 5문항 요청.

## Global Constraints

- wire ID `v2_localLLM`, Python namespace `kplasma_agent.v2_local_llm`, 계획 스키마 2·최종 답변 스키마 1을 유지한다.
- 보호 대상 그래프 구현, local 그래프의 노드·분기·계산·HITL·검증 규칙·프롬프트와 최종 UI/응답 양식을 바꾸지 않는다.
- planner는 실제 `submit_plan` 도구 호출 1개를 `message.tool_calls[].function.arguments`에서 받는다. 본문 JSON 우회, 필드명 변경, 문법 자동 수선, 스키마 완화는 하지 않는다.
- d1 모델·`/v1/systemone`·판단 규칙은 유지한다. 계획 검토 ON, 최대 재계획 2회, 최대 답변 재작성 1회, 호출 timeout 90초, 요청 예산 600초·13회 모델 호출을 유지한다.
- 입력 최대 16,000토큰, context 32,768, 동시 요청 1개를 출발점으로 한다. 초과 입력을 자르지 않는다. 실패를 숨기거나 예산·입력 한도를 임의로 완화하지 않는다.
- 질문·실험 데이터·계획·답변은 인증된 고정 loopback 서버로만 보낸다. proxy·redirect·상용 모델 fallback·외부 관측 전송을 거부한다. 인터넷·업데이트·모델 다운로드는 허용하고 OS 차단은 추가하지 않는다.
- 실데이터 150 Run과 원시 평가 자료는 Git 밖에 둔다. 코드 저장소에는 모델 가중치·키·실제 `.env`·실제 응답/스크린샷을 넣지 않는다.
- 이번 웹 접수는 Q01~Q05 각 1회, 합계 5회다. API 모드 접수 0회, 나머지 35문항 접수 0회다. 그래프 내부 재계획과 인공 준비 검사는 이 문항 수와 별도로 집계한다.
- 기존 dirty tree와 사용자 앱·대화·모델 세션을 보존한다. 전환 실패 시 다른 프로세스나 모델을 임의로 종료하지 않는다.

이 문서는 원계획의 Qwen MLX 실행 선택과 이번 평가 범위를 대체하는 후속 계획이다. 원계획의 복제 작업 전체를 다시 실행하지 않으며, 이후 사용자가 제외한 OS 송신 차단 조건도 복원하지 않는다.

## 결정과 근거

사용자는 LM Studio 유지와 llama.cpp 직접 실행의 차이를 검토한 뒤 **llama.cpp 전환 → 생각 모드 → 첫 5문항 확인** 순서를 선택했다. LM Studio+GGUF만 바꾸는 방식은 필요한 native 인자 제약의 적용 여부가 미확인이고, MLX 엔진 수정은 별도 엔진 유지보수가 필요하므로 이번 구현에서 제외한다. 여러 엔진을 선택하는 일반화 계층도 만들지 않는다.

현재 Qwen 요청에는 이미 `strict: true`가 있다. 공개 MLX의 Qwen 보호 문법은 도구 이름·태그를 제한하지만 인자 내용에는 임의 문자열을 허용한다. 반면 고정 llama.cpp의 Qwen3.5 대응 parser는 문자열이 아닌 배열·객체 인자에 JSON 스키마를 적용한다. 다만 문자열 인자의 enum 등 모든 제약을 강제하지는 않으므로 기존 Python 검증은 계속 필요하다. 우리 스키마 전체의 실제 수용 여부는 Task 1에서 확인하고, 실패하면 우회 없이 중단한다. [MLX 소스](https://github.com/lmstudio-ai/mlx-engine/blob/ea1160901f67bad16a377f44219df4b56f8cddaf/mlx_engine/tool_runtime.py#L593), [llama.cpp 소스](https://github.com/ggml-org/llama.cpp/blob/b12317/common/parsers/qwen3-coder.cpp#L98)

계획 생각 모드만 먼저 켜는 것은 이번 계획의 구현 제안이다. 계획 품질의 병목에 집중하고 writer JSON/SSE의 변경을 줄이기 위한 선택이며, 사용자가 모든 Qwen 역할의 생각 모드를 지정한 것으로 해석하지 않는다.

### 시작 프로필

| 항목 | 결정 |
| --- | --- |
| Qwen 파일 | `unsloth/Qwen3.5-9B-GGUF`의 `Qwen3.5-9B-Q4_K_M.gguf` 1개. 구현 시작 시 revision·파일 SHA-256·GGUF 내 tokenizer/template 정보를 잠근다. |
| Qwen model alias | `unsloth/Qwen3.5-9B-GGUF:Q4_K_M` |
| Qwen API | `http://127.0.0.1:8082/v1`. LM Studio의 1234와 d1의 8081을 점유하지 않는다. 포트 충돌 시 다른 서버에 붙지 않는다. |
| 실행 파일 | 이미 준비한 공식 macOS arm64 llama.cpp `b12317`와 동봉 라이브러리의 검증된 해시를 재사용한다. d1 프로세스는 교체하지 않는다. |
| Qwen 실행 옵션 | `--jinja`, `--ctx-size 32768`, `--parallel 1`, `--batch-size 512`, `--ubatch-size 512`, `--device MTL0`, `--gpu-layers all`, `--fit off` |
| 운영 옵션 | `--host 127.0.0.1`, `--port 8082`, 별도 `--api-key-file`, `--offline`, `--no-webui`, `--no-context-shift`, `--sleep-idle-seconds 1`, `--timeout 90` |
| 추론 분리 | `--reasoning auto`, `--reasoning-format deepseek`, `--reasoning-budget 2048`. 요청별 `chat_template_kwargs.enable_thinking`으로 계획 ON·답변 OFF를 명시한다. |
| planner 요청 | `reasoning_effort=medium`, 생각 ON, 전체 출력 최대 6,000토큰. 생각 예산 2,048도 이 전체 출력·context·90초 예산 안에서 사용한다. `medium` 문자열만으로 활성화를 주장하지 않는다. |
| writer 요청 | `reasoning_effort=none`, 생각 OFF, 기존 최대 출력 3,000과 JSON/SSE 계약 유지. |
| sampling | 비교 가능한 고정 시작값으로 Qwen 요청에 `temperature=0.6`, `top_p=0.95`, `top_k=20`, `min_p=0`, `presence_penalty=0`, `repeat_penalty=1`을 명시한다. 최적값을 입증한 설정은 아니며 기존 서버 기본값과 같다고 주장하지 않는다. |

Q4_K_M은 기존 MLX 4비트와 같은 양자화 방식이 아니다. 이번 5문항 비교는 **실행 엔진·양자화·생각 모드·명시적 생성 설정을 바꾼 전체 구성 비교**이며 생각 모드 하나의 인과 효과로 보고하지 않는다. [모델 파일](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/blob/main/Qwen3.5-9B-Q4_K_M.gguf), [고정 서버 옵션/API](https://github.com/ggml-org/llama.cpp/blob/b12317/tools/server/README.md), [Qwen 생성 설정 안내](https://huggingface.co/Qwen/Qwen3.5-9B#best-practices)

## Review Focus

1. 본문이나 `reasoning_content`에만 계획이 있어도 도구 호출 성공으로 처리하지 않는다. Task 1의 native 경계 검사로 고정한다.
2. 재계획·답변 전환 시 생각 설정과 실제 입력 계산이 달라지거나 이중 특수 토큰이 붙지 않아야 한다. Task 2에서 서버 usage와 대조한다.
3. d1이 깨어 있는 동안 Qwen을 깨우지 않으며, 대기 상태 점검 자체가 모델을 깨우지 않아야 한다. Task 2에서 순서와 메모리를 검사한다.
4. 모델·template·sampling·생각 예산을 바꾸면 이전 READY·메모리 증거·checkpoint를 재사용하지 않아야 한다. Task 1~2에서 fingerprint 경계를 검사한다.
5. 평가 제한이 누락되거나 실패 경로를 타도 6번째 문항과 API 모드가 접수되지 않아야 한다. Task 3에서 실행 전 행렬과 호출 금지 검사를 추가한다.

## 변경 파일 지도

경로의 `LOCAL`은 아래 표에서만 `agent/python/src/kplasma_agent/v2_local_llm/`의 약칭이다.

| 파일 | 책임 |
| --- | --- |
| `LOCAL/config.py`, `LOCAL/runtime-manifest.json` | 새 고정 모델·runtime 프로필, 역할별 생성 설정과 fingerprint |
| `LOCAL/model_client.py`, `LOCAL/core/model_gateway.py` | 원래 도구/JSON 경계를 유지하면서 요청별 생각 설정과 실제 alias 사용 |
| `LOCAL/runtime.py` | GGUF·실행 프로세스 검사, 양쪽 서버의 sleep 확인, 새 증거에 따른 준비 판정 |
| `LOCAL/core/budget.py`, `LOCAL/worker.py` | llama.cpp의 실제 template/tokenizer를 사용하는 Qwen 입력 계산과 주입 |
| `LOCAL/intentional-differences.json`, `LOCAL/worker-source.json` | 이번 전송·준비 경계 변경만 기록. 최초 clone 증거는 수정하지 않음 |
| `agent/python/evals/local_llm_smoke.py`, `agent/python/evals/local_llm_measure.py` | 새 alias·생각 프로필·native counter를 쓰는 기존 인공 검사 재사용 |
| `agent/python/evals/run_flow.py`, `agent/python/evals/test_flow_eval.py` | 기존 40문항 은행을 유지하면서 웹 첫 5개만 선택 |
| `agent/python/tests/v2_local_llm/`의 아래 task별 테스트·`runtime_helpers.py` | 실제 변경 경계에 필요한 회귀 검증과 인공 fixture |
| `.env.local-llm.example`, `scripts/agent/local-llm.mjs`, `scripts/agent/local-llm.test.mjs` | 비밀값 없는 실행 예시·host 안내를 새 환경에 맞춤. wrapper의 worker-only 책임 유지 |
| `docs/development/agent-v2-local-llm.md`, `docs/development/agent-v2-evaluations.md` | 실제 구현·검증 뒤 실행법과 범위 갱신 |
| `docs/verification/2026-11-13-v2-local-llm-llamacpp-web5.md` | 후속 구현 시 집계 결과 작성. 실행일이 달라지면 실제 날짜 사용 |

새 provider 프레임워크·UI·DB migration·엔진 fork·통합 서버 런처는 추가하지 않는다. 모델 서버는 기존처럼 별도 준비하고, `local-llm.mjs start`는 준비된 환경의 private worker만 시작한다.

## Task 1: GGUF 프로필과 native 도구 호출 연결

**Files:** `LOCAL/config.py`, `LOCAL/runtime-manifest.json`, `LOCAL/model_client.py`, `LOCAL/core/model_gateway.py`, `.env.local-llm.example`; 테스트는 `test_config.py`, `test_model_client.py`, `test_model_gateway.py`, `test_native_plan.py`.

**Interfaces:** 기존 `Settings.from_env(env_file)`, `Settings.versions()`, `V2LocalLLMSettings.from_env(base)`, `ModelClient._tool_request(...)`, `ModelClient._json_request(...)`와 `call_submit_plan(...)`의 소비자 계약을 유지한다. `Settings.model`과 두 gateway client가 새 alias를 사용하고, `versions()`가 실제 역할별 설정을 fingerprint에 포함하도록 한다.

- [ ] 구현 직전 변경 파일의 현재 상태·해시·기존 private 프로필을 비공개 경로에 보존한다. 사용자가 수정 중인 파일은 되돌리지 않는다.
- [ ] 위 GGUF 파일만 다운로드하고 immutable revision·크기·SHA-256을 확인해 manifest에 기록한다. 가중치·다운로드 cache·키는 Git 밖에 둔다. 기존 MLX 파일·template는 보존한다.
- [ ] 테스트를 먼저 추가한다: 새 alias가 gateway까지 전달됨, planner와 writer 설정 분리, 모델/생각/template/sampling/출력 예산 변경 시 fingerprint 변경, 비밀값은 fingerprint 출력에 노출되지 않음.
- [ ] 추가 경계 테스트를 먼저 실패시킨다: 정상 native 한 호출 허용, 본문-only·reasoning-only·복수/다른 도구·깨진 JSON·잘림·추가 필드 거부. 기존 PlanDraft와 tool schema의 변경 전후 hash는 같다.
- [ ] client의 기존 전송에 요청별 `chat_template_kwargs`, 분리된 reasoning 형식, 고정 sampling을 전달한다. `V2LocalLLMSettings.from_env`의 MLX model/생각 OFF 하드코딩을 고정 프로필에 맞춘다. 모델 응답 envelope는 그대로 둔다.
- [ ] `reasoning_content`는 최종 본문·SSE·계획 인자로 합치지 않는다. usage에 실제 reasoning token 수가 없으면 생성하거나 추정하지 않는다.
- [ ] 새 Qwen 서버를 다른 모델과 메모리 상주가 겹치지 않게 준비한다. 준비 단계의 인공 검사로 원래 `submit_plan.parameters` 전체가 컴파일·호출되는지 확인한다. 이 단계의 프로토콜 검사는 생각 OFF로 실행하고, Task 2에서 실제 생각 ON을 검증한다. Task 2 완료 전 실데이터 worker를 실행하지 않는다.
- [ ] 기존 `model_lease()` 아래에서 유효 계획 복사 1개와 중첩 배열/참조를 포함한 인공 계획 1개를 실제 native 호출로 검사한다. 공급한 계획과 의미·필드가 같은지 비교한다. 작동한다고 스키마 일부를 빼거나 본문 JSON으로 받지 않는다.
- [ ] 위 경계 테스트를 통과시키고 이번 전송 변경만 `intentional-differences.json`에 기록한다. upstream 문자열 제약의 빈틈은 기존 validator로 거부하며 엔진을 fork하지 않는다.

Task 1의 실제 원래 스키마 호출이 실패하면 원인·호출 결과를 보존하고 전환 미검증으로 보고한다. 다음 실문항 평가로 넘어가지 않는다.

## Task 2: 생각 모드·입력 계산·메모리·준비 판정 연결

**Files:** `LOCAL/runtime.py`, `LOCAL/core/budget.py`, `LOCAL/worker.py`, `LOCAL/config.py`, 관련 manifest, `evals/local_llm_smoke.py`, `evals/local_llm_measure.py`; 테스트는 `test_model_runtime.py`, `test_native_token_counting.py`, `test_budget.py`, `test_readiness.py`, `test_runtime_contract.py`, `test_runtime_measurement.py`와 기존 runtime 인공 helper.

**Interfaces:** `ModelRuntime.prepare(role: str) -> None`, `model_lease()`와 `make_input_guard(settings, *, qwen_count=None, d1_count=None, prepare=None)`를 유지한다. `core/budget.py`에 `make_qwen_counter(settings, client)`를 추가하며 반환 함수의 계약은 `count(payload, role) -> int`다. worker·smoke·contract probe·memory 측정이 같은 counter를 사용한다. `runtime.py`의 `runtime_profile(settings) -> dict`로 측정과 검증에서 같은 모델 실행 프로필을 만든다.

- [ ] 준비 판정 테스트를 먼저 추가한다: 다른 GGUF·alias·binary·template·실행 인자·context·sampling·생각 예산 또는 이전 MLX 측정 결과를 제시하면 `ready:false`여야 한다. 과거 checkpoint/PASS를 새 fingerprint에서 이어 쓰지 않는다.
- [ ] Qwen의 LM Studio `/api/v1/models`, load/unload API, 앱 설치 경로 검사와 `lms load` 호출을 제거한다. Qwen도 d1처럼 고정 서버의 `/props`·실제 listener PID·실행 파일/라이브러리 hash·명령 인자를 검사한다. alias만 맞는 다른 모델은 거부한다.
- [ ] Qwen의 HF tokenizer 디렉터리를 필수로 요구하던 준비 조건은 GGUF 내 tokenizer/template 검증으로 대체한다. 새 counter가 서버의 실제 내장 tokenizer를 쓰는데도 옛 MLX/HF 경로가 없다는 이유로 막히는 조건을 남기지 않는다. d1의 tokenizer·검토 계약은 유지한다.
- [ ] role 전환 테스트를 먼저 추가한다: `plan`/`answer` 전에는 d1의 `is_sleeping:true`, `plan_review`/`review` 전에는 Qwen의 `is_sleeping:true`를 확인한다. sleep 대기 한도는 기존 12초를 유지하고 실패 시 다음 모델을 깨우지 않는다.
- [ ] 두 서버를 `--sleep-idle-seconds 1`로 운영한다. 상태 점검에는 모델을 깨우지 않는 `GET /props`·`GET /health`만 사용한다. 서버 초기 시작도 한쪽 sleep 확인 뒤 다른 쪽을 시작한다. 모델 소유권 lock과 요청 종료 후 해제 확인을 유지한다.
- [ ] `make_qwen_counter`는 실제 호출과 같은 messages·tools/response_format·생각 설정으로 `/apply-template`을 호출하고, 받은 prompt를 `/tokenize`에 `add_special=false`, `parse_special=true`로 보낸다. schema를 추정으로 중복 삽입하거나 이중 BOS를 붙이지 않는다. 반환 count가 잘못되면 추론 전에 거부한다.
- [ ] 인공 입력으로 planner native tool, writer 일반 JSON, writer SSE의 서버 `usage.prompt_tokens`와 사전 계산을 대조한다. 한글·`m⁻²s⁻¹`·중첩 schema·생각 ON/OFF·16K 경계/초과를 테스트한다. 일치하지 않으면 readiness를 통과시키지 않는다.
- [ ] 실제 planner 응답에서 생각이 분리되어 생성되고 최종 native 도구 호출로 종료되는지 확인한다. writer는 생각 OFF와 원래 JSON/SSE를 검사한다. 기존 thinking OFF override 파일을 새 서버에 적용하지 않는다.
- [ ] 기존 인공 메모리 측정 6행(Qwen writer/d1 × 입력 목표 256/4096/15500)을 새 counter·프로필로 갱신한다. 여기에 원래 도구 스키마를 포함한 16K 이내 장문 planner 생각 ON 호출 1행을 추가해 총 7행과 전체 스택의 메모리를 측정한다. tool schema 자체가 큰 planner를 256토큰 사례로 억지 축소하지 않는다.
- [ ] `runtime_profile(settings)`에는 모델/양자화·가중치/바이너리/template hash·context/batch/동시성/GPU·역할별 sampling/생각/출력 예산을 포함하고 backend URL·worker token·UI 세션은 제외한다. 같은 모델로 측정한 인공 스택과 격리 평가 스택의 주소 차이 때문에 측정이 무효가 되지 않게 한다. checkpoint에는 기존 전체 `configFingerprint`를 별도로 사용한다.
- [ ] `verify_memory_report`가 위 7행·새 fingerprint·실제 thinking 설정을 검증하도록 함께 갱신한다. 준비 통과 기준은 기존처럼 전 표본 메모리 압력 정상·추가 swap 0·각 호출 90초 이내다. 기존 MLX의 메모리 보고서를 재사용하지 않는다.
- [ ] 측정/계약 검사 중 장애·불일치는 기존 blocker로 유지한다. READY 우회 flag, 자동 CPU fallback, 입력 자르기, 모델 변경으로 통과시키지 않는다. 관계없는 LM Studio 모델이 메모리 여유를 차지해도 무단 종료하지 않는다.
- [ ] `status`가 실제 `ready:true`가 되는 것을 확인하고 실행 문서를 갱신한다. 실패하면 관측치와 blocker를 보고하고 5문항 평가를 보류한다.

준비용 인공 호출은 웹 정답 평가가 아니다. 실제 호출 횟수와 소요 시간을 별도 기록하며, 이 검사로 품질 동등성이나 장시간 안정성을 선언하지 않는다.

## Task 3: 기존 평가기를 웹 첫 5문항으로 제한

**Files:** `agent/python/evals/run_flow.py`, `agent/python/evals/test_flow_eval.py`, `docs/development/agent-v2-evaluations.md`. `flow_grader.py`와 비공개 문항·정답은 변경하지 않는다.

**Interfaces:** `build_jobs(cases, *, mode="both", limit=40)`로 확장한다. CLI `--mode {both,browser,api}`(기본 both), `--limit 1..40`(기본 40)을 추가한다. 기본 실행은 기존 40 browser + 40 API를 그대로 유지하되 이번 실행은 반드시 `--mode browser --limit 5`로 고정한다.

- [ ] 테스트를 먼저 추가해 `build_jobs(bank, mode="browser", limit=5)`의 행렬이 정확히 `(Q01,1,browser)`부터 `(Q05,1,browser)`까지이고 API 행은 없음을 확인한다. 전체 은행 40개·중복 없음 검사는 유지한다.
- [ ] 잘못된 mode/limit, 39개 은행, 중복 ID는 worker·HTTP 접수 전에 거부한다. 옵션 없는 기존 80행 테스트는 그대로 통과시킨다.
- [ ] CLI→행렬→manifest의 planned/total→진행 출력까지 선택 범위를 전달한다. 하드코딩된 40/80 문구와 합계를 실제 행렬 길이로 바꾼다. 제어 흐름 중단으로 80회 실행기를 간신히 멈추는 방식을 재사용하지 않는다.
- [ ] browser-only 테스트에서는 `run_api` 호출을 실패하도록 대체해 마지막 문항 종료·문항 실패·정리 경로 모두 API를 호출하지 않는 것을 검증한다. 동일 문항 실패를 새 trial로 자동 재접수하지 않는다.
- [ ] offline preflight가 서버·worker·브라우저·모델을 시작하지 않으며 정확히 browser 5/API 0 계획을 내보내는지 확인한다.

후속 구현 뒤 preflight 명령(변수는 비공개 보관 경로이며 secret 값은 아님):

```sh
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m evals.run_flow \
  --bundle "$KPLASMA_EVAL_BUNDLE" --output "$KPLASMA_QUICK_PREFLIGHT" \
  --graph-version v2_localLLM --mode browser --limit 5
```

## Task 4: 회귀 확인 후 Q01~Q05 웹 평가·번호별 보고

**Files:** 기존 검증 helper와 Task 3 평가기를 재사용한다. 새 집계 문서는 변경 파일 지도에 명시한 verification 파일에 쓴다. 원문·수치·화면·DB export는 새 비공개 output 디렉터리에 둔다.

**Interfaces:** 기존 `flow_grader.grade`, `export_request`, `summarize`와 `result.json`/`results.jsonl`을 재사용한다. 최초 계획 통과와 재계획 후 최종 통과를 분리하고 모델 호출·시간·failure code를 실제 journal에서 집계한다.

- [ ] 아래 오프라인 회귀를 실행한다. clone·응답 계약 검사에 포함되는 보호 대상 그래프 소스 비교는 유지한다.

```sh
# 저장소 루트. local unit tests + 평가기 검사이며 실모델 평가가 아니다.
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m pytest \
  -q agent/python/tests/v2_local_llm agent/python/evals/test_flow_eval.py --tb=short
node --test scripts/agent/local-llm.test.mjs
git diff --check
```

- [ ] 기존 CI 기준 `uv run --project agent/python --frozen ruff check agent/python/src agent/python/tests agent/python/evals`와 `uv run --project agent/python --frozen mypy agent/python/src`를 실행한다. 실제 명령·결과와 기존 실패를 구분해 기록한다. clone의 최초 증거·프롬프트·스키마 기준을 다시 만들어 통과시키지 않는다.
- [ ] 원래의 150 Run frozen bundle을 **변경 없이** 격리 평가 DB에 공급한다. 기존 문항 파일 SHA-256은 `3e4648ad1ee51f952a212d859369c7c8a764ad77e3587f15b37a9fea32ed0e9c`, 첫 ID는 Q01~Q05다. Run 수·version·oracle가 맞지 않으면 접수 전에 중단한다.
- [ ] Task 2 메모리 증거와 평가용 worker의 `runtime_profile`이 같음을 확인하고, 바뀐 backend의 계약/준비 검사는 새 전체 fingerprint에서 수행한다. backend/DB/UI는 이전처럼 전용 평가 환경을 재사용해 준비하고, 원래 앱의 150 Run과 과거 대화는 수정하지 않는다.
- [ ] private worker `status` 통과 뒤 전용 브라우저에서 아래 명령으로 5회만 접수한다. API 읽기로 상태·snapshot을 확인하는 것은 허용하되 API 모드의 별도 질문 접수는 하지 않는다.

```sh
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m evals.run_flow \
  --bundle "$KPLASMA_EVAL_BUNDLE" --output "$KPLASMA_QUICK_RESULTS" \
  --connection "$KPLASMA_QUICK_CONNECTION" --env-file "$KPLASMA_LOCAL_PROFILE" \
  --graph-version v2_localLLM --mode browser --limit 5 --live
```

- [ ] 각 문항은 기존 순서·원문·선택 문맥·정답으로 1회 실행한다. 인프라가 정상인 경우 모델/정답 실패도 그대로 보존하고 다음 문항을 진행한다. 메모리 압력·준비 실패·다른 활성 요청·버전 오염이 발생하면 남은 접수를 중단하고 실제 완료 수만 보고한다.
- [ ] 실제 UI와 동일 request의 snapshot을 연결해 확인한다. 예상 밖 사용자 입력 요구는 임의 답변하지 않고 기존 취소/실패 규칙으로 기록한다. 외부 대화 전환 간섭이 있으면 모델 오류와 분리한다.
- [ ] 자동 점수는 원래 grader로 계산한다. 별도 내용 검사로 검색 조건·엄격/포함 경계·결과 Run·순서·요청하지 않은 설명·단위 중복·가짜 성공을 확인한다. 자동 통과와 요청 준수 통과를 섞지 않는다.
- [ ] 실패 원인은 native 호출/JSON·스키마 형식, 계획의 논리·질문 해석, d1 검토, 최종 응답, 인프라·평가 간섭으로 구분한다. 형식 통과와 정답을 같은 지표로 세지 않는다.
- [ ] 완료 후 browser 5개 고유 요청, Q01~Q05, API 모드 0, 여섯 번째 문항 0을 확인한다. 평가용 소유 프로세스만 정리하고 원래 앱·모델 파일·대화 상태를 보존한다.
- [ ] 보고서를 다음 열로 작성하고 채팅에도 번호별로 요약한다: `번호/ID | 이전 자동 결과 | 새 최초 계획 형식 | 재계획 수 | 새 자동 결과 | 요청 준수 | 시간 | 실패 원인`.

현재 확인한 비교 기준:

| 순서 | ID | 이전 자동 결과 |
| --- | --- | --- |
| 1 | Q01 | 통과 |
| 2 | Q02 | 실패 |
| 3 | Q03 | 실패 |
| 4 | Q04 | 실패·예상 밖 입력 요구로 취소 |
| 5 | Q05 | 실패 |

비교 기준은 **1/5**다. 브라우저 시나리오 시간에는 모델 로딩·worker 준비·UI 확인이 포함되므로 순수 추론 속도로 부르지 않는다. 첫 5개는 모두 `lookup_search` 범주여서 비교·중첩·HITL·개념 설명의 개선을 이 결과로 판정하지 않는다.

## 완료·중단·복구

- 구현 연결 완료: 원래 native 도구 계약·writer JSON/SSE·d1 검토·새 토큰 계산·24GB 준비 판정이 모두 실제로 통과한다.
- 평가 완료: Q01~Q05의 실제 결과 5개와 API 접수 0 증거를 보존한다. 5/5 정답을 만들기 위해 문항·정답·검증을 바꾸거나 실패 문항을 재실행하지 않는다.
- 품질 결과: 자동 정답률, 최초/복구 형식 통과율, 요청 준수, 지연을 따로 보고한다. 실패가 남아도 원인을 구분해 보고하고, 이번 결과를 기존 상용 v2와 동등하다고 표현하지 않는다.
- 지원하지 않는 schema·실제 생각 활성화 실패·token count 불일치·추가 swap·90초 초과가 나오면 해당 단계 실패로 기록한다. 새 엔진 빌드·CPU fallback·추가 양자화·40문항 재평가로 범위를 자동 확대하지 않는다.
- 복구가 필요하면 이번 작업 소유 서버·worker만 종료하고 구현 직전에 보존한 local 전송 경계 파일·private 프로필로 복원한다. 원래 MLX 모델 파일과 원본 template는 지우지 않는다. 자동 cloud/MLX fallback은 추가하지 않는다.
- 이번 계획 단계에서는 모델 다운로드, 제품 코드 변경, 실제 모델 호출, 웹 평가, commit/push/PR을 실행하지 않는다. 다음 구현은 이 계획의 순서로 진행하고, 완료 시 실제 실행 명령과 결과를 남긴다.

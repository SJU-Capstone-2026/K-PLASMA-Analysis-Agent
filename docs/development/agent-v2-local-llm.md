# v2_localLLM 실행 준비와 검증

`v2_localLLM`은 보존한 v2를 별도 Python namespace로 복제한 그래프다.

현재 코드 체크포인트는 [LocalLLM_v2.1](../verification/2026-11-13-local-llm-v2.1.md)이다. 그래프 식별자와 응답 양식은 유지하며, 메모리 경고에 따른 시작 제한은 남아 있다.
정확한 wire ID는 `v2_localLLM`, Python 패키지는 `kplasma_agent.v2_local_llm`이다.
v2·v3 구현이나 공통 cloud worker를 실행 중에 빌려 쓰지 않는다.
현재 코드는 계획·답변에 Qwen3.5-9B GGUF Q4_K_M, 두 의미 검토에 d1-2B GGUF Q8_0를 사용한다.
학습·fine-tuning은 필요하지 않다.

## 2026-11-13 실행 환경 전환

최신 후속 검증에서는 Docker VM 메모리를 사용자 지정3GiB로 제한하고 DB 검사·새 인공7행 검사를 통과한 뒤,
Q01~Q05 웹 자동 정답5/5·자동 UI 검사5/5를 완료했다. 최초 계획 즉시 채택2/5, 재계획 합계3회이며 d1 계획 검토는5회 모두PASS였다.
추가 swap0·관측 critical0이지만 웹673개 표본 중 warning174개가 남았다. Mac 전체의 기존 resident 계산 지표 최대는19.942GiB다.
Q03 결측 사유 안내와 mobile 표 가독성은 수동 보완 사항으로 남는다. [최신 검증·피크 기록](../verification/2026-11-13-v2-local-llm-docker-3gib.md).
준비 안정화 수정 자체와 이전 swap 발생 결과는 [이전 검증 기록](../verification/2026-11-13-v2-local-llm-stable-web5.md)을 따른다.

Qwen은 별도 llama.cpp b12317 Metal 서버의 `127.0.0.1:8082/v1`에 연결한다.
모델 alias는 `unsloth/Qwen3.5-9B-GGUF:Q4_K_M`이며 계획·재계획은 생각 ON,
답변·재작성은 OFF다. 입력 16K·Qwen context 24K(24,576)·전체 출력 계획 6,000/답변 3,000·생각 예산 2,048·호출 90초를 사용한다. d1 context 32K는 유지하며 24K 프로필의 메모리 증거는 별도로 검증한다.
생각 문자열은 최종 응답·SSE에 합치지 않는다. native `submit_plan`과 원래 스키마·그래프를 유지한다.
Qwen batch/ubatch는 256/256이며 d1 batch/ubatch 16,000/16,000은 유지한다. 실행 인자·메모리 증거도 이 설정과 일치해야 한다.

Qwen도 `--sleep-idle-seconds 1`을 사용한다. 반대쪽 모델의 sleep 확인 뒤에만 다음 모델을 깨우며,
LM Studio 설치·load/unload API·별도 HF tokenizer 디렉터리를 준비 조건으로 사용하지 않는다.
두 서버의 실제 GGUF tokenizer로 template 전체를 계산하고 usage와 대조한다.
runtime 설정·생각 모드가 다른 과거 메모리 보고서와 checkpoint는 재사용하지 않는다.

최초 native 계약 확인 뒤에는 두 모델이 sleep이고 메모리 압력이 5초 연속 정상일 때 준비를 허용한다.
이 안정화 대기는 최대 60초이며 warning이나 깨어난 모델을 관측하면 연속 정상 시간을 다시 센다.
critical은 즉시 실패한다. 시작 전·검증 캐시가 있는 워커 폴링의 현재 압력 검사와 인공 메모리 증거 검증은 유지한다.
이는 준비 판정 시점을 바꾼 것으로, 호출 중 warning이나 swap을 없앴다는 뜻은 아니다.

이전 MLX의 아래 실측 기록은 새 GGUF 환경의 준비 증거를 대신하지 않는다.
새 프로필은 별도 인공 계약·메모리 준비 검사를 통과해야 실데이터 worker를 시작한다.
서버 실행 옵션·검증 순서는 [전환 계획](../plans/2026-11-13-001-v2-local-llm-llamacpp-thinking-web5.md)을 따른다.

2026-11-13 새 프로필의 단독 native 호출·생각 ON은 확인했다. 최초 32K 전체 스택 검사는 추가 swap 644.19MiB로 실패했고,
후속 24K 검사도 warning·추가 swap 160.93MiB로 실패했다. 이 두 시도에서는 Q01~Q05를 실행하지 않았으며 활성 private 실행 프로필도 승격하지 않았다.
상세 범위와 원인은 [전환 검증 기록](../verification/2026-11-13-v2-local-llm-llamacpp-web5.md)과
[24K 재검사 기록](../verification/2026-11-13-v2-local-llm-24k-memory.md)을 따른다.

후속 Qwen batch/ubatch 256 검사에서는 추가 swap 0이었지만 warning으로 준비 판정이 실패했다.
이 256 검사 시도에서도 d1 실제 추론과 Q01~Q05는 미실행이었다. [256 검사 기록](../verification/2026-11-13-v2-local-llm-24k-batch256-memory.md).

## 이전 MLX 환경에서 확인한 범위

2026-11-12 Apple M4 Pro·통합 메모리 24GiB에서 확인했다.
Python 3.12.15와 잠금 의존성, LM Studio 0.4.28+2/MLX 1.14.0, Qwen3.5-9B MLX 4비트와 d1-2B Q8_0가 준비되어 있다.
d1은 Metal 오류가 있는 b11960 대신 공식 llama.cpp b12317을 사용하며 GPU 추론을 확인했다.
모델·실행 파일의 고정 해시는 패키지의 `runtime-manifest.json`에 있다.

사용자는 이후 OS 수준 송신 필터를 필수 조건에서 제외했다. 업데이트·모델 다운로드는 허용하고,
질문·실험 데이터의 상용 LLM 전송과 cloud fallback을 막는다. 아래 실행 지침은 원래 계획서의 OS 필터 관련 조건보다 이 변경을 우선한다.

입력 계산은 실제 서버 usage와 대조했고 준비 검사는 실제 `ready:true`를 반환했다.
두 모델의 큰 GPU 버퍼를 함께 유지하면 메모리 부족이 발생해 모델을 번갈아 상주시키는 방식으로 수정했다.
약 23.5K 입력은 최초 측정에서 통과했지만 재측정에서 메모리 압력 warning·추가 swap 약 161MiB가 발생했다.
그 결과 최대 입력을 16K로 낮추었으며 초과 입력을 자르지 않고 추론 전에 거부한다.
16K 재측정은 여섯 요청 성공·메모리 압력 전 표본 정상·추가 swap 0을 확인했다.
이는 장시간 안정성이나 기존 상용 v2와의 판단 품질 동등성을 뜻하지 않는다.
초기 JSON 본문 방식의 인공 질문 평가에서 계획 누락과 거짓 승인을 발견했다.
계획 수신은 이후 실제 `submit_plan` 도구 호출로 복구했다. 답변 작성용 JSON과 그래프·최종 응답 schema는 유지한다.
번호별 초기 결과는 [검증 기록](../verification/2026-11-12-v2-local-llm.md), 현재 도구 호출 경계는
[native 복구 기록](../verification/2026-11-12-v2-local-llm-native-tools.md)을 따른다.

## 명령

비밀값 없는 예시는 [.env.local-llm.example](../../.env.local-llm.example)에 있다.
명시적으로 선택한 별도 로컬 파일을 사용하며 루트 `.env`나 cloud 설정으로 대체하지 않는다.
실제 `.env.local-llm`과 모델·원시 검증 출력은 Git에 올리지 않는다.

```sh
node -- scripts/agent/local-llm.mjs status --env-file .env.local-llm
node -- scripts/agent/local-llm.mjs smoke --env-file .env.local-llm
node -- scripts/agent/local-llm.mjs start --env-file .env.local-llm
```

- `status`는 private worker의 `--check`를 호출한다. 준비됐으면 exit 0, 누락·차단·불명확이면 안전한 blocker 코드와 exit 2를 반환한다. host 정보와 기본 설치 경로 점검은 참고 사실이며 준비 증거를 대신하지 않는다.
- `smoke`는 내장 인공 문자열만 고정 loopback 모델 서버로 전송한다. 실제 질문·Run·DB·대화 파일을 받는 옵션이 없다. 성공은 프로토콜 검증 성공이며 `runtime_ready=false`와 남은 검증을 함께 출력한다.
- `start`는 같은 준비 검사를 통과한 뒤 `kplasma_agent.v2_local_llm.worker`만 시작한다. private worker가 다시 검증하며 공통 v1/v2 worker를 fallback으로 실행하지 않는다. 고정 파일·실제 실행 설정·현재 메모리와 실측 결과·인공 모델 계약을 검사하며, 누락이나 불일치는 blocker로 반환한다.

환경 파일이 없거나 `--skip-privacy` 같은 알 수 없는 옵션을 주면 프로세스를 시작하지 않는다.
파일을 shell에서 `source`하지 않는다. 경로·비밀값을 명령 인자로 펼치거나 provider 오류 원문을 출력하지 않는다.
모델·backend·전용 UI를 임의로 기동한 것만으로 `start`의 준비 검사를 우회할 수는 없다.
이 wrapper가 backend·DB·frontend·브라우저를 자동 시작하거나 bootstrap을 자동 주입하지는 않는다.

## 공통 backend와 화면 준비

2026-11-13 사용자 승인에 따라 기존5173 웹·8080 backend·DB·storage를 함께 사용한다.
그래프 구현과 모델 실행 워커는 버전별로 유지하며, DB·서버를 별도로 복제할 필요는 없다.
backend의 기존 `DB_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `KPLASMA_STORAGE_ROOT`는 보존한다.
`AGENT_WORKER_TOKEN`은 기존 상용 워커 키로 유지하고, 서로 다른 `AGENT_LOCAL_WORKER_TOKEN`을 추가한다.
로컬 워커의 `AGENT_V2_LOCAL_LLM_WORKER_TOKEN`은 이 로컬 키와 같아야 한다. 혼합 배포에서 키가 없거나 같으면 시작을 거부한다.
기존 local-only 배포는 `AGENT_WORKER_TOKEN`만 사용하는 방식도 호환한다.

```sh
# 위 비밀값이 해당 backend의 환경에만 준비된 터미널에서 실행한다.
SERVER_ADDRESS=127.0.0.1 AGENT_SUPPORTED_GRAPH_VERSIONS=v1,v2,v3,v2_localLLM \
AGENT_DEFAULT_GRAPH_VERSION=v2_localLLM AGENT_LOCAL_RUNTIME_ENABLED=true \
AGENT_LOCAL_UI_ORIGIN=http://127.0.0.1:5173 AGENT_LOCAL_API_HOST=127.0.0.1:8080 \
backend/gradlew -p backend bootRun

# frontend 터미널: 비밀 token은 VITE_ 변수에 넣지 않는다.
VITE_AGENT_SUPPORTED_GRAPH_VERSIONS=v1,v2,v3,v2_localLLM VITE_AGENT_DEFAULT_GRAPH_VERSION=v2_localLLM \
VITE_API_TARGET=http://127.0.0.1:8080 npm run dev
```

backend에는 별도의 `AGENT_LOCAL_BOOTSTRAP_TOKEN`도 제공해야 한다. 32바이트 이상의 무작위 값을 사용하고 명령 출력·로그·공유 설정에 남기지 않는다.
사용할 브라우저에서 `#local-bootstrap` fragment를 화면에서 즉시 제거하고 `/api/local-runtime/session`에 `X-Local-Bootstrap` 헤더로 한 번 교환한다.
bootstrap은 비공개 로컬 실행 경로로만 전달하며 URL query·로그·공유 문서에 넣지 않는다. UI 세션과 worker·모델 API의 token은 서로 다르다.
브라우저는 로컬 세션 인증 뒤에만 데이터에 접근한다. OS 필터 설치나 브라우저별 인터넷 차단은 요구하지 않는다.

상용 키는 로컬 요청을 claim하거나 요청별 context·checkpoint·입출력 API를 읽거나 쓸 수 없다. 반대 방향도 제한한다.
공통 화면에서는 모든 저장 판단 기록을 볼 수 있지만, 상용 워커의 기억 조회에는 상용 출처로 확인된 기록만 제공한다.
출처는 서버 내부 `decision.origin_graph_version`에 보존하며 공개 응답 JSON은 바꾸지 않는다. 출처가 불명확한 기존 기록도 상용 워커에서는 제외한다.
대화는 첫 질문의 그래프 버전을 유지한다. 다른 버전은 기존 규칙대로 새 대화에서 선택한다.

## 준비 순서

먼저 실데이터에 접근하지 않는 준비 환경에서 의존성과 모델을 확보한다.
가중치·tokenizer·chat template의 snapshot revision과 SHA-256, LM Studio/MLX engine·llama.cpp 버전과 실행 파일을 기록한다.
업데이트·모델 검색·다운로드는 허용한다. 분석 요청은 설치한 로컬 모델에만 연결하며 실패해도 원격 모델로 대체하지 않는다.
소스에는 가중치나 실제 payload를 복사하지 않는다.

고정한 모델 서버에는 로컬 전용 token을 설정하고 loopback만 bind한다.
초기 주소는 Qwen `127.0.0.1:1234/v1`, d1 `127.0.0.1:8081/v1/systemone`이다.
기존 backend의 8080 포트와 d1 서버를 충돌시키지 않는다. 포트가 사용 중이면 다른 서비스에 붙지 않는다.
모델 API token과 worker token은 전용 UI에 전달하지 않는다.

`smoke`는 private 복제본의 실제 `submit_plan` schema·PlanDraft·답변 schema를 사용한다.
동일한 `submit_plan.parameters`를 도구 정의로 등록하고 실제 도구 호출 한 개를 받는다. 중첩 계획 인자, 한국어·`m⁻²s⁻¹`, writer JSON, SSE delta와 최종 JSON의 일치, d1의 명명된 choice·전체 확률을 검사한다.
빈 계획·다른 도구·복수 도구 호출·잘린 인자·추가 답변 필드·완료 신호 없는 SSE·잘못된 확률·redirect는 실패다.
사용량은 서버가 제공한 token counter만 보고한다. d1이 usage를 제공하지 않으면 `null`이며 임의로 추정하지 않는다.
현재 planner는 `/v1/chat/completions`에 `tools=[submit_plan]`, `tool_choice=required`, `parallel_tool_calls=false`를 보내고
`message.tool_calls[].function.arguments`만 계획으로 받는다. 본문의 계획 JSON을 대신 읽는 fallback은 없다.
writer는 원래의 답변 JSON schema와 SSE projector를 유지한다. 계획 지침·도구 인자 schema·PlanDraft 검증·그래프 순서·최종 응답 스냅샷도 유지한다.

`base_revision`에 한해 native XML의 `None`/`null` 문자열과 양의 정수 문자열을 실제 nullable 정수로 변환한다.
`steps`/`requirements`는 JSON 문자열로 감싼 목록일 때 한 번만 decode한다. 그 외 값은 기존 strict 검증기로 검사한다.
사용자 조건·단위·지표·단계를 만들어 넣지 않으며, 깨진 JSON이나 허용되지 않은 필드를 삭제해 통과시키지 않는다.
인자 검증에 실패하면 실제 오류 경로·자료형·이유를 기존 `generation_failure` 재계획 문맥에 포함한다.
그래프의 노드·분기·최대 2회 재계획은 유지하며, 오류를 보고하는 보조 함수만 이 정보를 전달한다.
요청이 끝나면 소유한 Qwen을 해제하고, 대기 중 일시적인 메모리 경고는 정상 상태가 될 때까지 새 요청을 claim하지 않고 기다린다.
환경·모델 파일·계약 불일치 등 다른 준비 실패는 계속 실행을 차단한다.

### 초기 연결 검증 기록 — 후속 수정 전

인공 질문만 사용했고 DB·실험 Run·실데이터 worker는 실행하지 않았다. 이 결과로 `runtime_ready`를 올리지 않는다.

- LM Studio `0.4.28+2`는 `/Applications/LM Studio.app`에 설치했다. 이 앱은 사용자 `~/Applications`에서 실행하지 못하며, 별도 `llmster` daemon과 동시에 실행하지 않는다.
- Qwen은 계획의 고정 revision `8b2b98c00a6b4d291155e4890773ca8f769aee53`를 받았고 파일 13개의 크기와 LFS SHA-256을 검증했다. MLX engine `1.14.0`, context `32768`, 동시 요청 `1`을 사용했다.
- 모델 기본 Jinja override는 원본 template 앞에 `{%- set enable_thinking = false %}`만 추가한다. 원본 가중치·tokenizer 파일은 수정하지 않았다. override SHA-256은 `e175bc0107b113da24d85536756d0fd6254ba95a1a685ebfeaba25b06fc97155`다. Context Overflow는 `Stop at Limit`이며 실제 예산 계산과의 일치 검증은 남아 있다.
- LM Studio의 `/v1/responses`는 이 설정에서 native tool의 `null`을 `"None"` 문자열로 반환하거나 JSON 형식을 지키지 않았다. 공식 [Structured Output 문서](https://lmstudio.ai/docs/developer/openai-compat/structured-output)의 Chat Completions 경로로 active planner/writer 경계를 연결했다. 생성 실패·거절·잘림을 기존 실패로 처리하며, reasoning 내용은 최종 답변으로 승격하지 않는다. planner 최대 출력 `6000`, writer `3000`을 유지한다.
- Qwen과 d1은 `127.0.0.1`에만 bind했다. Qwen 인증·전용 token을 설정했고, 두 서버 모두 인증 누락/오류는 `401`, 올바른 키는 `200`이었다. LM Studio의 로컬 네트워크 공개·외부 MCP·CORS는 껐다. `sk-lm-` 키는 LM Studio의 로컬 키 형식이며 cloud `sk-` 키와 구분한다. 키와 실제 profile은 Git에서 제외한 비공개 파일에만 둔다.
- d1은 고정 revision `4a181094d1b6addfaa3a0956f78e7ab2aa406a0c`, Q8_0 SHA-256 `073313d92b53b0ac8193db6e906cb3c78a98183d244b15b7b8f5426115c6738c`, llama.cpp `b11960`을 사용했다. 이 빌드의 Metal kernel 컴파일이 실패해 이번 연결 검사는 CPU로 수행했다. context/batch/microbatch는 `8192`, 동시 요청은 `1`이었다. GPU 동작이나 장문 처리 성공으로 해석하지 않는다.
- 실제 `smoke --live`는 계획 JSON·writer JSON·SSE·d1 choice를 모두 통과했다(`6.811초`, 짧은 인공 입력 1회). 사용량은 제공된 실제 counter만 기록했다. 성능 벤치마크가 아니다.
- 별도 인공 질문의 실제 gateway 연결에서는 Qwen 계획이 스키마·코드 검증을 통과했고, 그 계획을 받은 d1이 검토 3항목에 `PASS`를 반환했다. 계획 `11.485초`, CPU 검토 `20.836초`였다. 이 검사는 인공 입력 크기 제한만 주입한 직접 연결 검사이며, 실데이터용 tokenizer·네트워크 준비 검사를 통과시킨 것이 아니다.
- 같은 인공 개념 질문으로 실제 독립 그래프도 실행했다. Qwen 계획 → d1 계획 검토 `PASS` → Qwen 답변의 3회 호출로 `executionStatus=COMPLETE`, `graphVersion=implementationId=v2_localLLM`인 기존 응답 스냅샷을 생성·검증했다. 재계획 `0회`, 총 `35.795초`였다. Run 없이 인메모리 journal만 사용했고, guard는 인공 입력 크기 제한이었다. 이 결과도 실데이터 worker의 준비 판정을 대체하지 않는다.

연결 변경 후 `agent/python`에서 `.venv/bin/python -m pytest -p no:cacheprovider tests/v2_local_llm -q --tb=short`를 실행해 `298 passed`를 확인했다(`initial_clone` marker 등록 경고 3건). 변경한 client/gateway는 Ruff와 mypy를 통과했다. 추가 v3 실행 검사는 수행하지 않았다.

위 목록은 최초 연결 시점의 기록이다. 이후 GPU·입력 계산·메모리·준비 판정 수정 결과와 구분한다.

## 데이터 전송 범위와 준비 판정

모델 요청은 정해진 literal loopback 주소·포트만 허용한다.
외부 base URL·redirect·환경 proxy·cloud 자격 증명 상속·외부 관측 exporter와 cloud fallback은 거부한다.
LM Studio의 로컬 네트워크 공개·외부 MCP·CORS는 끄고 모델 API 인증을 사용한다.
화면과 API에는 기존 로컬 세션·Host·Origin 검사를 유지한다. 모델·worker token은 화면에 전달하지 않는다.
OS 송신 필터·LuLu·맥 전체 인터넷 차단은 준비 조건이 아니다.

`status`는 GGUF 모델과 llama.cpp 실행 파일의 SHA-256, 실제 Qwen/d1 프로세스의 빌드·GPU·context·batch·sleep 인자,
profile에 대응하는 메모리 측정 결과와 현재 메모리 압력을 확인한다.
실제 인공 요청으로 계획 schema·writer JSON·SSE·d1 choice/확률·token counter도 확인한다.
준비 flag만 넣어 통과할 수 없다. 최초 검사에서는 모델을 로딩/해제하며 시간이 걸린다.
워커는 자신의 프로세스에서 다시 검사하고, claim 사이에도 설정과 현재 상태를 확인한다.
워커·평가·상태 검사의 실제 모델 호출은 같은 프로세스 간 잠금을 사용한다. 다른 호출이 모델을 사용 중이면
새 계약 검사는 `LOCAL_MODEL_RUNTIME_BUSY`로 반환하며 실행 중인 모델을 해제하지 않는다.

준비 판정은 모델 연결과 실행 환경의 판정이다. 분석 품질 평가 통과나 모든 질문의 성공을 보증하지 않는다.

## 로컬 입력 예산

LocalLLM_v2.1부터 사용하지 않는 Hugging Face tokenizer 경로와 Transformers 의존성을 제거했다.
준비 환경에서 잠금 파일에 맞춰 설치한다. 모델 가중치를 이 명령이 다운로드하지는 않는다.

```sh
uv sync --project agent/python --frozen --extra tracing
```

private worker는 복제본의 `make_input_guard(settings, qwen_count=..., d1_count=..., prepare=...)`를 사용한다.
Qwen은 인증된 llama.cpp의 `/apply-template`과 `/tokenize`로 system/user·도구 정의·생각 설정·출력 계약을 반영한 입력을 계수한다.
실제 서버 usage와 일치하는 native counter를 사용하며 문자 수·다른 모델의 인코딩·별도 Hugging Face tokenizer로 대체하지 않는다.
native counter가 준비되지 않으면 입력을 보내지 않고 실패한다. 토큰 수를 맞추기 위해 원문을 자르지 않는다.

Qwen은 `min(16000, context_tokens - 6000)`을 적용한다.
d1은 출력 생성이 없어 6000 토큰을 예약하지 않으며 각 질문의 전체 입력이 `min(16000, context, batch, microbatch)` 이하여야 한다.
16K는 사용자 문장만의 길이가 아니다. 지시·계획·질문별 검토 내용·template·도구/출력 계약에 필요한 토큰을 포함한다.
고정 GGUF의 `systemone` template·선택지 정렬·특수 토큰 escape를 재현한 뒤 인증된 native `/tokenize`로 계산한다.
한국어·유니코드·특수 토큰을 포함한 실제 d1 usage와 일치를 확인했다. 전체 질문의 usage 합계를 한 질문의 context 길이와 혼동하지 않는다.
입력 초과 시 질문·근거·이력을 조용히 자르지 않고 기존 실패/검토 불가 경로를 따른다.
기존 `check_payload(..., count=...)`는 고정 응답 테스트용이며 실제 워커의 계수를 대체하지 않는다.

## 메모리와 실제 평가

d1의 512 microbatch 분할 실험은 native 서버가 긴 입력을 거부하여 채택하지 않았다.
Qwen은 GGUF Q4_K_M, context24576, batch/microbatch256, GPU `MTL0`, parallel1을 사용한다.
현재 d1 설정은 GPU `MTL0`, context `32768`, batch/microbatch `16000`, parallel `1`, `--sleep-idle-seconds 1`이다.
추가로 `--fit off --no-context-shift --offline --no-webui --timeout 90`과 loopback·API key file을 사용한다.

Qwen 작업은 d1의 sleep 상태를 확인한 뒤 시작하고, d1의 token 계산·검토 전에는 Qwen의 sleep 상태를 확인한다.
두 서버의 `--sleep-idle-seconds 1`로 모델 버퍼가 순차 상주한다. 계획은 생각ON, 답변은 생각OFF를 유지한다.
LM Studio나 별도 Hugging Face tokenizer 디렉터리는 필요하지 않으며 다른 앱이나 모델을 임의로 종료하지 않는다.

재현 명령은 아래와 같다. 고정 모델 서버가 준비된 상태에서 별도 인공 DB·backend·화면·브라우저를 생성하고 측정 후 정리한다.
실제 실험 파일을 받는 옵션은 없다. 출력 폴더와 원시 측정 결과는 Git에 넣지 않는다.

```sh
npm run measure:agent:local -- --env-file .env.local-llm
```

출력된 `measurement.json`을 로컬 보관 경로로 옮기고 `AGENT_V2_LOCAL_LLM_MEMORY_MEASUREMENT_PATH`에 절대 경로를 기록한다.
메모리 결과의 모델 revision·runtime·context·batch가 profile과 다르면 준비 검사는 거부한다.
동시성 1, 짧은/중간/약 15.5K 입력·짧은 출력에서 검사하며 원래 90초 호출·600초 요청 예산은 유지한다.
6K에 이르는 최대 출력이나 장시간 반복 실행까지 검증한 결과는 아니다.

실제 품질 평가는 `plan_review_enabled=true`를 유지한다. 최초 계획과 재계획 뒤 결과,
거짓 승인·거짓 반려·형식 오류·실행 결과·지연을 분리한다. 원시 결과는 로컬에만 두고 새 유료 cloud 비교는 실행하지 않는다.
준비 검사 전체에는 여러 모델 호출과 로딩이 필요하므로 launcher의 검사 대기는 최대 600초다. 개별 모델 호출의 90초 상한을 늘린 것은 아니다.

## 합성 검증

```sh
node --test scripts/agent/local-llm.test.mjs
agent/python/.venv/bin/python -m pytest -p no:cacheprovider agent/python/tests/v2_local_llm/test_runtime_contract.py -q
```

위 테스트는 인공 child process와 HTTP transport를 사용하며 실제 모델·방화벽·외부 수신 여부를 입증하지 않는다.
실제 모델 연결·환경 준비 판정과 분석 품질 판정은 구분한다. OS 수준 송신 검증은 이 버전의 필수 조건이 아니다.

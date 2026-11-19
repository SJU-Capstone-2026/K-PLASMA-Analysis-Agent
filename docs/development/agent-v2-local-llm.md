# v2_localLLM 실행 준비와 검증

[v2.3 체크포인트](../verification/2026-11-15-local-llm-v2.3-checkpoint.md)는 v2.2 미커밋 작업을 포함한 현재 보존 범위다. 2026-11-15 사용자 결정에 따라 영어화·중복 축약·정리표 제외를 유지하며, d1 오류 검출 문제는 v2.4에 넘기는 미해결 항목으로 기록한다.

[v2.3 실측 결과](../verification/2026-11-15-local-llm-v2.3-mlx8-single.md): 최종 영어·축약 입력은 Q8 기존 입력보다 토큰 19.6%·검토 시간 19.3%를 줄였지만, 인공 계획의 기대 판정 일치는 3/5에서 2/5로 낮아졌다. 현재 설정은 정확도 유지가 검증된 운영 권장값이 아닌 요청된 실험 구성이다.

`v2_localLLM`은 v2를 별도 Python namespace인 `kplasma_agent.v2_local_llm`으로 복제한 독립 그래프다. 기존 5173 웹·8080 backend·DB·storage를 공유하고, 그래프와 모델 워커는 버전별로 분리한다. v2·v3의 구현을 실행 중에 빌려 쓰지 않는다.

v2.5의 모델 구성은 **Qwen llama.cpp + d1 MLX 8비트 개별 검토**다. d1은 검사 하나씩 순서대로 처리하며 MLX BF16 개별 경로도 비교·복구용으로 남긴다. 새 설정의 메모리 준비와 품질 비교 결과는 별도 증거로 확인한다. [v2.3 모델 구성](../plans/2026-11-15-003-local-llm-v2.3-mlx8-single.md), [v2.5 평가](../verification/2026-11-18-local-llm-d1-checklist-10.md).

| 역할 | 현재 설정 |
|---|---|
| 계획·재계획 / 답변·재작성 | Qwen3.5-9B GGUF Q4_K_M, llama.cpp b12317, `127.0.0.1:8082/v1` |
| 계획 의미 검토 / 필요한 답변 검토 | LiquidAI/d1-2B, MLX affine8/group64, `127.0.0.1:8083/v1/systemone` |
| d1 비교 경로 | 같은 MLX 서비스의 BF16, 같은 개별 처리 |
| 자원 | Docker VM 1536MiB, Qwen context 24576·batch/ubatch 256, d1 context 32768·개별 입력 16000 이하 |
| 검토·복구 예산 | 계획 검토 ON, 요청 전체 재계획 최대 2회, 필요한 답변 검토·재작성 최대 1회 |

그래프 노드·분기·HITL·최종 응답·SSE·저장 snapshot은 유지한다. d1의 예전 llama.cpp·공동 입력 16개·독립 병렬 4개 경로는 현재 실행 구성에서 제거한다. **Qwen의 llama.cpp는 계속 사용한다.**

## d1 MLX 모델과 서비스

MLX는 Apple Silicon용 별도 Python 환경에서 실행한다. 공유 worker의 가상환경에 MLX를 설치하지 않는다. 고정 버전은 `mlx-decision` 1.3.0, commit `2527a733c97a3fd5e0de54ea19f74fd362ed1ad2`, MLX 0.32.4다.

```sh
uv sync --project agent/python/runtimes/d1_mlx --frozen
```

8비트 파일은 고정한 `LiquidAI/d1-2B` BF16 snapshot에서 로컬 변환한다. 기존 GGUF Q8_0 파일을 MLX에서 재사용하는 방식이 아니다. 변환 대상은 Linear 153개이며, tied embedding·norm·convolution은 BF16으로 둔다. tokenizer·calibration·검토 readout과 원본 파일은 보존한다. 양자화가 판정에 미치는 영향은 비교 실험으로 확인한다.

```sh
agent/python/runtimes/d1_mlx/.venv/bin/python \
  agent/python/runtimes/d1_mlx/convert.py \
  --source .local/models/d1-bf16/<고정-snapshot> \
  --output .local/models/d1-mlx8/<새-변환-폴더>
```

위 `<...>`는 확보한 로컬 폴더 이름으로 바꾼다. 변환기는 네트워크를 사용하지 않고 기존 출력 폴더를 덮어쓰지 않는다. source manifest와 파일 SHA를 검사한 뒤 원본 revision·양자화 설정·변환 파일 SHA·source manifest SHA를 새 `kplasma-manifest.json`에 기록한다.

비공개 서비스 설정의 예시는 다음과 같다. `.local/runtime/d1-mlx.json`에 두며 `model_path`는 실제 고정 폴더로 바꾼다.

```json
{
  "model_path": ".local/models/d1-mlx8/<고정-변환-폴더>",
  "token_file": ".local/runtime/d1-mlx-token.txt",
  "port": 8083,
  "precision": "q8",
  "group_size": 1,
  "independent_batch_size": 1
}
```

```sh
agent/python/runtimes/d1_mlx/.venv/bin/python \
  agent/python/runtimes/d1_mlx/service.py \
  --config .local/runtime/d1-mlx.json
```

토큰 파일은 0600으로 관리한다. 서비스는 loopback에만 바인딩하고 모든 API에 Bearer 인증을 요구한다. worker와 서비스의 모델 폴더·정밀도·token·포트·처리 크기가 일치해야 한다. `group_size=1`, `independent_batch_size=1`만 허용한다.

비밀값 없는 설정은 [.env.local-llm.example](../../.env.local-llm.example)에 있다. `AGENT_V2_LOCAL_LLM_D1_ENGINE=mlx`, `D1_PRECISION=q8`, `D1_MODEL=LiquidAI/d1-2B:MLX8`, `D1_INPUT_PROFILE=en-compact-no-view`를 사용한다. 이 문서에서 생략한 `D1_` 설정에도 접두사 `AGENT_V2_LOCAL_LLM_`를 붙인다.

BF16 비교는 별도 구현 없이 서비스 `precision=bf16`·BF16 `model_path`, worker의 `D1_PRECISION=bf16`·`D1_MODEL=LiquidAI/d1-2B:BF16`·`D1_MODEL_PATH`를 함께 바꾼다. revision·메모리 증거도 해당 프로필과 맞춰야 한다. 실패 시 BF16으로 자동 우회하지 않는다.

## d1 입력 변경과 소규모 비교

입력 변경은 로컬 전송 표현에만 적용한다. 질문·이력·계획·인용 근거를 번역하거나 원본 snapshot을 다시 쓰지 않는다.

| 입력 프로필 | d1에 보내는 표현 |
|---|---|
| `ko-full` | 기존 한국어 전체 입력 |
| `en-full` | 고정 검토 지침·선택지·정책·도구 설명을 영어로 제공 |
| `en-compact` | 영어 입력에서 반복 지표 정의는 공통 사전과 참조로 제공하고 추적 hash는 전송에서 제외 |
| `en-compact-no-view` | 위 입력에서 계획의 실행 정리표 `execution_view`를 전송에서 제외 |

32개 지표의 이름·단위·정의와 전체 검사항목·순서·선택 ID는 유지한다. 원본 계획·`check_specs`·`program_effects`를 보존하고, 원래 digest와 `execution_view`도 저장 snapshot에는 남긴다. 답변 검토의 고정 지시도 영어화하되 답변·근거는 원문을 유지한다. 입력 계수와 실제 전송은 같은 표현을 사용한다.

이번 비교는 동일한 인공 계획 5개에 대해 BF16/한국어 전체 → Q8/한국어 전체 → Q8/영어 전체 → Q8/중복 축약 → Q8/정리표 제외의 **5구성 × 5입력 × 1회 = 검토 HTTP 요청 25개**다. 요청 안의 검사항목은 각각 하나씩 순차 추론한다. Qwen 계획을 새로 생성하는 웹 5문항 재평가와는 다르다.

실험 명령 예시다. `agent/python` 디렉터리에서 해당 phase와 정확히 일치하는 비공개 env·서비스 설정을 준비하고, 존재하지 않는 출력 파일을 지정한다.

```sh
.venv/bin/python -m evals.local_llm_d1_v23_probe \
  --env-file ../../.local/runtime/v2.3-mlx8-single/q8-no-view.env \
  --phase q8-no-view \
  --output ../../.local/runtime/v2.3-mlx8-single/q8-no-view.json
```

나머지 phase는 `bf16-baseline`, `q8-baseline`, `q8-english`, `q8-compact`다. 각 phase의 precision/input profile이 다르면 시작을 거부한다. 실제 그래프 상태의 `plan_review_enabled=true`도 확인한다. 이 비교의 preflight는 파일·실행 사실·그래프 상태를 확인하며 숨은 readiness 추론을 추가하지 않는다.

추가 추론 예산은 메모리 준비 7요청(Qwen 4/d1 3), 필요 시 최종 worker 준비 최대 4요청(Qwen 3/d1 1)이다. 비교와 합쳐 상한 36 HTTP 요청이며 token count는 별도 집계한다. 반복 warmup·자동 재실험·72건 평가·상용 비교를 추가하지 않는다.

검사 1개당 평균 입력 토큰은 **전체 입력 토큰 합 / 전체 검사 수 합**으로 계산한다. 판정·검사별 이유·새 오승인/오반려·전체 지연·실제 모델 처리 시간·메모리 피크·swap을 구분한다. 1회 비교만으로 일반적인 속도·정확도 동등성을 보증하지 않는다.

## v2.4 검사별 도구·지표 설명 선별

[최신 전체 선별 결과](../verification/2026-11-15-local-llm-d1-all-check-context.md): 정상 5개·오류 5개의 모든 62개 검사에 선별을 적용했다. 계획당 d1 검토는 평균 8.928초, 검사당 입력은 2,140.89토큰이다. [이전 부분 선별](../verification/2026-11-15-local-llm-d1-per-check-context.md)의 11.553초·2,763.21토큰보다 22.72%·22.52% 줄었고 62개 판정은 모두 같았다. 정상 5/5, 의도한 오류 항목·사유 검출 1/5로 정확도 문제는 남아 있다. 현재 공용 워커는 사용자 지시에 따라 `per_check`로 유지한다.

[최초 v2.4 계획](../plans/2026-11-15-004-local-llm-d1-per-check-context.md)과 [모든 검사 선별 보완 계획](../plans/2026-11-15-005-local-llm-d1-all-check-context.md)은 검사별 MLX 입력의 `tool_contracts`만 줄인다. 질문·이력·원본 계획·검사 지침·선택지·검사 목록·원본 snapshot과 digest는 보존한다. 모델·영어화·검사별 단일 처리·그래프·최종 응답 계약은 같다.

- 현재 실행 설정과 예시는 worker의 `AGENT_V2_LOCAL_LLM_D1_CONTEXT_MODE=per_check`, MLX 서비스 JSON의 `context_mode: "per_check"`다. 두 값을 반드시 맞춘다. 설정 키를 생략하면 하위 호환용 full로 동작하므로 선별 실행에는 명시한다. full은 비교 옵션으로 남아 있다.
- 모델을 추가 로딩하거나 검사별 HTTP 요청으로 나누지 않는다.
- 항상 생성하는 작업·필터·사용자 확인 누락 검사는 각각 고정 설명 묶음을 제공한다. 나머지 10종류는 검사별 도구·지표군·단위·참조 설명을 복사한다. 출력 지표 검사는 32개 정의를 유지하면서 무관한 도구를 제외하고, 빈 정렬 목표에도 검색 지표 6개를 제공한다. 알 수 없는 표현이나 불완전한 참조는 안전하게 원본 전체 문자열을 보낸다.
- 모드·선별 버전·선별기·registry·언어 투영과 계약 의존성의 소스 hash를 서비스 시작 identity, worker 설정·메모리 증거·복구 fingerprint에 연결한다. 설정 또는 실행 중 소스가 다르면 준비 판정을 차단한다. 옛 메모리 증거로 새 코드를 준비 완료 처리하지 않는다.
- `/v1/count`와 추론은 같은 선별·pack 경로를 쓴다. 내부 응답의 검사별 packed hash, 선별/전체 유지/fallback, 토큰 수와 실제 usage를 대조한다. 이 진단 정보는 최종 사용자 응답에 추가하지 않는다.

`evals.local_llm_d1_context_probe`는 SHA를 고정한 기존 정상 5개·오류 5개를 한 모드에서 한 번씩만 검사한다. per_check 평가에서는 모델 호출 전과 실제 추론 후 모두 62개 전부 selected를 요구하며, full/fallback을 전체 선별 성공으로 세지 않는다. 별도 준비 증거가 필요하고 모델·실제 그래프의 계획 검토 ON, Q8+MLX 단일 처리, 캐시 OFF와 Docker 1536MiB를 확인한다. 최신 회차는 의미 검토 10회와 메모리/워커 준비 11회를 분리했으며, 이전 full 기준을 재실행하지 않았다. 추가 warmup·재시도·정답 변경은 자동 실행하지 않는다.

```sh
cd agent/python
.venv/bin/python -m evals.local_llm_d1_context_probe \
  --env-file <private-local.env> \
  --corpus <private-frozen-corpus.json> \
  --output <new-private-result.json>
```

전체 설명과 선별 설명의 정확도·오류 항목·정확한 사유·추가 오판·토큰·시간·메모리를 함께 비교한다. 기존과 같은 오답을 유지한 결과는 검토 정확도 통과가 아니며, 결과를 확인하기 전에는 입력 감소나 속도 향상을 보장하지 않는다. 원시 입력·응답·메모리 산출물은 Git 제외 로컬 경로에 보관한다.

## v2.5 d1 숫자 검토 입력

`per_check`와 `en-compact-no-view` 조합은 v2.4의 도구·지표 설명 선별 뒤에 `d1-context-3` 검토 복사본을 만든다. 원본 질문과 인용문을 유지하고, 독립적인 숫자 필터 검사에는 현재 지표의 실행값만 남긴다. 복사본의 숫자 인용은 `citation.quote`로 표시하고, 실행 계획에서는 기존 `source.quote`를 사용한다. `check_specs`에는 전체 검사 목록을 싣고 현재 검사를 첫 위치에 둔다. 실제 `questions`는 검사 한 개다.

- 공통 지침은 이력이 있는 경우에만 이력을 언급한다. 미래값과 사용자 선택 안내는 검사에 관련된 `result_ref`, `await_input`, 실행 전 조건을 따라 붙인다. 숫자가 원문과 다를 때 통과시키지 않는 기존 문구와 선택지는 유지한다.
- 누락·정렬 검사와 값이 비어 있거나 다른 단계의 결과에 의존하는 숫자 검사는 기존 계획을 그대로 읽는다. 지원하지 않는 입력 계약은 기존 경로로 처리한다. `full`과 다른 언어·입력 프로필도 기존 동작을 유지한다.
- 개수 계산과 추론은 같은 검사별 복사본을 사용한다. 결과 파싱·실행은 원본 계획과 검사 목록을 사용한다. 그래프, 최종 JSON/SSE, 저장 계약과 재계획·재작성 한도는 그대로다.

실제 Qwen 계획을 고정한 정상 5개와 숫자 오류 5개에서 **정상 PASS 5/5, 실제 오류 항목 검출 5/5, 사유까지 정확 4/5**였다. 검사 목록이 빠진 직전 발췌 구성은 정상 PASS 3/5, 오류 항목·사유 5/5였다. 계획당 d1 채점은 6.926→7.062초, 검사당 입력은 1,987.18→2,046.93토큰이었다. 두 숫자는 동일한 56개 검사의 기록이며 웹 질문 전체 시간은 별도다. [실험 조건과 오판 내역](../verification/2026-11-18-local-llm-d1-checklist-10.md).

## Qwen 계획·응답과 캐시

계획·재계획은 생각 ON(예산 2048, 전체 출력 최대 6000), 답변·재작성은 OFF(출력 최대 3000)이며 호출 제한 90초를 유지한다. 생각 문자열은 최종 답변이나 SSE에 합치지 않는다. 선택 extra `local-llm-analysis`의 CPU tokenizer 진단은 추정값이며 실제 입력 제한은 native tokenizer를 사용한다.

planner는 `/v1/chat/completions`에 `tools=[submit_plan]`, `tool_choice=required`, `parallel_tool_calls=false`를 보내고 `message.tool_calls[].function.arguments`에서만 계획을 받는다. 본문의 계획 JSON을 대신 읽는 fallback은 없다. writer JSON schema·SSE projector도 유지한다.

v2.2의 `required_prior_outputs`는 **이번 단계 전에 필요한 앞 단계 출력의 조건**이다. 표시할 조회 지표가 아니다. 처음 하는 조회는 `depends_on: []`, `required_prior_outputs: []`다. `count`는 정확한 개수이며 추가 조건이 없으면 `count`·`value_type`·`unit`은 각각 `null`이다. [로컬 계획 schema](../contracts/agent-v2-local-llm.plan.schema.json).

과거 `requires`는 읽을 수 있지만 새 계획은 새 이름으로 직렬화한다. 두 이름을 동시에 보내면 거부한다. 기존 DB·대화·완료 기록을 일괄 변환하지 않고 fingerprint가 다른 미완료 checkpoint도 강제 재개하지 않는다. PlanDraft 버전2와 `native-submit-plan-chat-v2` 계약을 유지한다.

공용 웹의 활성 로컬 개발 실행은 Qwen 계획 디스크 KV 캐시와 d1 계획 검토를 기본 ON으로 사용한다. 새 설치 예시에서 Qwen 캐시의 초기값은 OFF다. 켜려면 `QWEN_PLAN_CACHE_ENABLED=true`, `QWEN_PLAN_CACHE_DIR=.local/cache/v2_localLLM/qwen-plan-cache-KV`와 같은 실제 서버의 `--slot-save-path`를 함께 설정하고 새 메모리·캐시 왕복 증거를 확보한다. 상대 경로는 프로젝트 루트 기준이다. 이 캐시의 적용 범위는 Qwen 계획과 재계획이다.

캐시 준비 검사는 저장·복원·실제 토큰 재사용·수치 보존·메모리와 d1 응답 계약을 확인한다. 인공 계획의 d1 `PASS`/`ISSUE`/`UNCLEAR`와 검사별 판정·점수는 원문 그대로 기록하고, 두 계획의 통과 여부는 `semantic_review_passed`로 별도 표시한다. 정상적인 반려 응답 자체를 캐시 고장으로 취급하지 않으며, 누락·불완전·잘못된 응답과 `UNAVAILABLE`/`SKIPPED`는 계속 준비 실패다. 실제 요청의 d1 반려·재계획 규칙은 유지한다.

활성 환경 파일과 모델 서버의 저장 경로를 함께 보존하고, ON으로 사용하기로 한 개발 실행을 평가 종료 후 OFF로 되돌리지 않는다. 사용자 승인 후 실제 ON 실행과 앞 5문항을 확인한 수치는 [캐시 ON 웹 비교](../verification/2026-11-18-local-llm-cache-on-web5.md)에 기록했다.

전용 폴더는 0700, 파일은 0600으로 관리하며 `.local/` Git 제외를 유지한다. 캐시에는 질문·계획이 포함될 수 있어 파일 동기화·로그·Git 공개 대상에서 제외한다. 완료 파일 2GiB·관리 파일 4GiB 보관 정책을 유지하고 임시 쓰기 피크는 따로 관측한다. 저장·복원 제한은 5초이며 손상·설정 불일치는 cache miss로 처리한다. 슬롯 초기화까지 실패하면 중단한다. miss를 이유로 모델 재호출이나 검토 생략을 추가하지 않는다. 이전 OFF/ON 결과는 [v2.2 기록](../verification/2026-11-14-local-llm-v2.2-qwen-plan-cache.md)을 따른다.

## 준비·메모리·입력 제한

Qwen이 sleep한 것을 확인하고 d1을 로드한다. d1은 GPU 동기화·참조 제거·캐시 해제 뒤 빈 서비스 메모리로 돌아온 것을 확인해야 Qwen을 다시 깨운다. Qwen은 `--sleep-idle-seconds 1`을 유지한다. MLX 서비스 프로세스가 살아 있는 것과 가중치가 상주하는 것은 구별한다. 다른 앱을 임의로 종료하지 않는다.

현재 개발 설정은 Docker VM **1536MiB**와 `MEMORY_POLICY=development`다. warning과 swap 변화를 기록하면서 허용하되 critical·알 수 없는 압력·해제 실패는 다음 모델 호출을 막는다. 기본 정책인 `strict`는 정상 압력·추가 swap 0 기준을 유지한다. Docker 상한은 VM 설정이며 worker 프로세스에 거는 메모리 상한이 아니다. 기존 DB·볼륨·Run을 보존하고 DB OOM도 확인한다.

준비 증거는 모델 revision·모든 파일 SHA·서비스/변환 helper·실제 설치 라이브러리·고정 lock·context·정밀도·입력 표현·캐시·메모리 정책과 연결된다. 예전 GGUF/BF16/다른 입력 프로필의 보고서로 새 프로필을 준비 완료 처리하지 않는다. 준비 flag만 넣어 통과할 수 없으며 전체 준비 검사는 실제 모델을 호출할 수 있다.

Qwen은 `/apply-template`·`/tokenize`, d1은 인증된 MLX count 경로에서 실제 template·검사지침·선택지까지 계수한다. Qwen 입력은 `min(16000, context_tokens - 6000)`, d1은 검사 하나당 `min(16000, context, batch, microbatch)` 이하다. 여러 검사의 usage 합을 한 검사의 context 길이로 해석하지 않는다. 한도 초과·계수 실패는 입력을 자르거나 검사 생략으로 통과시키지 않는다.

전체 스택 인공 메모리 준비 명령은 다음과 같다. 기존 원본 데이터를 받지 않고 별도 인공 DB·backend·화면을 측정 후 정리한다. 실제 모델 호출이 있으므로 위 실험 예산에 포함해 조정한다.

```sh
npm run measure:agent:local -- --env-file .env.local-llm
```

출력 `measurement.json`을 Git 제외 경로에 보관하고 `AGENT_V2_LOCAL_LLM_MEMORY_MEASUREMENT_PATH`로 지정한다. 고정 runtime·현재 실행 프로필과 맞지 않으면 준비 검사를 거부한다. 짧은/중간/장문 입력 검사는 최대 출력·장기간 반복 실행의 안정성 보증을 대신하지 않는다.

실제 평가는 모델 설정과 실제 그래프 `plan_review_enabled=true`를 확인한 뒤 수행한다. 최초 계획 통과, d1 지적, 재계획 뒤 최종 통과·실패를 구분한다. 준비·상태 검사도 같은 프로세스 간 모델 잠금을 사용한다. 잠금 사용 중에는 새 검사가 `LOCAL_MODEL_RUNTIME_BUSY`로 끝나며 실행 중인 모델을 해제하지 않는다.

## 공통 backend와 화면

기존 `DB_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `KPLASMA_STORAGE_ROOT`는 보존한다. 상용 `AGENT_WORKER_TOKEN`과 로컬 `AGENT_LOCAL_WORKER_TOKEN`은 다르게 설정하고, 로컬 worker의 `AGENT_V2_LOCAL_LLM_WORKER_TOKEN`은 로컬 키와 일치시킨다. 혼합 배포에서 키가 없거나 같으면 시작을 거부한다. local-only 배포의 기존 worker token 방식도 호환한다.

```sh
# 비밀값은 해당 backend의 환경에만 준비한다.
SERVER_ADDRESS=127.0.0.1 AGENT_SUPPORTED_GRAPH_VERSIONS=v1,v2,v3,v2_localLLM \
AGENT_DEFAULT_GRAPH_VERSION=v2_localLLM AGENT_LOCAL_RUNTIME_ENABLED=true \
AGENT_LOCAL_UI_ORIGIN=http://127.0.0.1:5173 AGENT_LOCAL_API_HOST=127.0.0.1:8080 \
backend/gradlew -p backend bootRun

# frontend 터미널: token을 VITE_ 변수에 넣지 않는다.
VITE_AGENT_SUPPORTED_GRAPH_VERSIONS=v1,v2,v3,v2_localLLM VITE_AGENT_DEFAULT_GRAPH_VERSION=v2_localLLM \
VITE_API_TARGET=http://127.0.0.1:8080 npm run dev
```

backend의 `AGENT_LOCAL_BOOTSTRAP_TOKEN`은 32바이트 이상의 무작위 값이다. 비공개 실행 경로로 브라우저 `#local-bootstrap` fragment에 전달한 뒤 즉시 지우고 `/api/local-runtime/session`의 `X-Local-Bootstrap` 헤더로 한 번 교환한다. URL query·로그·공유 문서에 값을 남기지 않는다. UI session·worker·모델 API token은 서로 다르다.

상용 키는 로컬 요청·context·checkpoint·입출력을 읽거나 쓸 수 없고 반대 방향도 제한한다. 화면에서는 기존 저장 판단 기록을 볼 수 있지만 상용 worker의 기억 조회에는 상용 출처로 확인된 기록만 제공한다. 서버 내부 `decision.origin_graph_version`으로 출처를 보존하고 공개 응답 JSON은 유지한다. 출처 불명확 기록도 상용 worker에서는 제외한다. 대화는 첫 질문의 그래프 버전을 유지하므로 버전 변경은 새 대화에서 선택한다.

## worker 명령과 데이터 전송 범위

공유 Python 환경은 `uv sync --project agent/python --frozen --extra tracing`으로 준비한다. 명시적으로 선택한 비공개 `.env.local-llm`만 사용하고 파일을 shell에서 `source`하지 않는다. 루트 `.env`·cloud 설정으로 대신하지 않는다.

```sh
node -- scripts/agent/local-llm.mjs status --env-file .env.local-llm
node -- scripts/agent/local-llm.mjs smoke --env-file .env.local-llm
node -- scripts/agent/local-llm.mjs start --env-file .env.local-llm
```

- `status`는 worker `--check`를 호출한다. 준비되면 exit 0, 차단·불명확이면 blocker와 exit 2다. 새 실행 identity의 계약 확인은 실제 모델을 호출할 수 있다.
- `smoke`는 인공 문자열로 native 계획·writer JSON·SSE·d1 choice/확률 프로토콜을 확인한다. 성공만으로 전체 메모리 준비나 정확도를 통과한 것은 아니다.
- `start`는 준비 검사 후 private local worker만 시작한다. backend·DB·frontend·브라우저·bootstrap을 자동 기동하지 않는다. worker도 현재 압력과 설정을 계속 확인한다.

모델 payload는 고정된 literal loopback 주소·포트로만 전송한다. 외부 base URL·redirect·환경 proxy·cloud 자격 증명 상속·외부 관측 exporter·cloud fallback은 거부한다. 화면과 API는 로컬 session·Host·Origin 검사를 유지하며 모델·worker token은 화면에 전달하지 않는다. 업데이트·다운로드는 허용하고 OS 송신 필터·LuLu·맥 전체 인터넷 차단은 요구하지 않는다.

가중치·실제 env·캐시·대화 원문·DB/실험 payload·원시 평가 로그는 Git에 넣지 않는다. 메모리 준비는 연결·실행 환경의 검증이며 상용 v2와 판단 품질이 같다는 보증이 아니다.

## 과거 검증 기록

아래 문서는 각 시점의 설정·측정 결과다. 현재 프로필의 준비 증거로 재사용하지 않는다.

- [LocalLLM_v2.1](../verification/2026-11-13-local-llm-v2.1.md), [v2.2 선행 출력 필드](../verification/2026-11-14-local-llm-v2.2-prior-outputs.md)
- [v2.2 Qwen 캐시](../verification/2026-11-14-local-llm-v2.2-qwen-plan-cache.md), [개발 메모리 정책](../verification/2026-11-14-local-llm-development-memory.md)
- [Docker 3GiB·앞 5문항 웹](../verification/2026-11-13-v2-local-llm-docker-3gib.md)
- [MLX BF16·공동 입력 비교](../verification/2026-11-14-local-llm-v2.3-qwen-d1-joint.md), [독립 병렬 4개 비교](../verification/2026-11-15-local-llm-d1-independent-batch4.md)

모델을 호출하지 않는 합성 확인 명령:

```sh
node --test scripts/agent/local-llm.test.mjs
agent/python/.venv/bin/python -m pytest -p no:cacheprovider agent/python/tests/v2_local_llm/test_runtime_contract.py -q
```

# Qwen 24K 전체 스택 메모리 재검사

날짜: 2026-11-13. M4 Pro / 통합 메모리 24GB, 독립 `v2_localLLM`.

## 결과

Qwen 문맥을 32,768에서 **24,576**으로 변경하고 전체 스택 메모리 검사를 다시 실행했다.
검사 결과는 **실패**이며 `ready:false`, blocker `LOCAL_MEMORY_EVIDENCE_INVALID`다.
사용자가 요청한 조건에 따라 Q01~Q05 웹 평가는 실행하지 않았다. **웹 접수 0 / API 접수 0**이다.

| 항목 | 실제 결과 |
| --- | --- |
| Qwen 서버 실제 context | 24,576 |
| 짧은 Qwen writer 입력 | 사전 계산 244 = 실제 사용량 244토큰 |
| 짧은 writer 결과 | JSON 정상, 생각 OFF, 5.122초 |
| 메모리 압력 표본 | 정상 `1` → warning `2`; 표본 4개 |
| 추가 swap | 168,747,336 bytes = **160.93MiB** |
| 시작 / 최대 resident 지표 | 18.15 / 21.52GiB |
| d1 실제 추론 | 메모리 중단으로 도달하지 못함, 0회 |
| 큰 입력 / 생각 ON planner 검사 | 미실행 |

resident는 기존 sampler의 active+wired+compressor 계산값이며 완전한 시스템 메모리 분해나 모델 RSS가 아니다.
이전 32K 검사의 추가 swap 644.19MiB보다 작지만 시스템 시작 상태도 달라 문맥 감소만의 효과라고 단정하지 않는다.
warning과 추가 swap으로 기존 준비 기준을 만족하지 못한 것이며 OOM이나 모델 응답 실패로 보고하지 않는다.

## 변경과 보존

- Qwen 기본값, 명시 프로필, 예시 설정을 24,576으로 맞췄다.
- 모델·양자화·엔진·Metal, batch/ubatch 512, 동시 요청 1, 계획 생각 ON / writer OFF를 유지했다.
- 전체 입력 최대 16,000, 생각을 포함한 계획 출력 최대 6,000 / 답변 3,000을 유지했다. 입력을 자르지 않는다.
- d1 context 32,768 / batch·ubatch 16,000과 기존 d1 프로세스·모델·검토 규칙은 유지했다.
- 실제 평가 gateway의 `plan_review_enabled=true`를 사전 확인했다. d1의 새 구성 추론 성공을 주장하지 않는다.
- 메모리 표본 전체 정상·추가 swap 0·호출 90초의 통과 기준을 완화하지 않았다.
- 기존 v2/v3 소스 49개 hash, local 그래프·도구·최종 답변 계약 파일, PlanDraft와 `submit_plan` 스키마의 변경 전 일치를 확인했다.
- 사용자 앱이나 기존 개발 프로세스를 임의로 종료하지 않았다. 이번 검사 소유 Qwen·백엔드·DB·웹·브라우저만 정리한다.
- 원시 측정·비밀 프로필은 Git 밖에 보존하며 활성 앱 프로필로 승격하지 않는다. 실패 증거를 READY 증거로 재사용하지 않는다.

## 재현과 검증

기존 모델 파일과 b12317을 사용했다. 새 다운로드·CPU/cloud fallback·추가 평가 접수는 없다.
비공개 프로필에는 `AGENT_V2_LOCAL_LLM_QWEN_CONTEXT_TOKENS=24576`,
`AGENT_V2_LOCAL_LLM_PLAN_REVIEW_ENABLED=true`를 지정하고 새 측정 경로를 사용했다.
Qwen 서버의 `--ctx-size`도 24576으로 맞췄다.

```sh
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
GRADLE_OPTS=-Dorg.gradle.daemon=false \
node -- scripts/agent/measure-local-llm.mjs --env-file "$KPLASMA_24K_PROFILE"
# exit 2: LOCAL_MEMORY_PRESSURE, 실패 measurement.json 보존

PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m pytest -q \
  agent/python/tests/v2_local_llm agent/python/evals/test_flow_eval.py \
  agent/python/evals/test_v2_harness.py agent/python/tests/test_graph_variants.py \
  agent/python/tests/test_eval_graph_versions.py --tb=short
# 458 passed, 기존 initial_clone marker 경고 3개

node --test scripts/agent/local-llm.test.mjs
# 7 passed

agent/python/.venv/bin/python -m ruff check agent/python/src agent/python/tests agent/python/evals
agent/python/.venv/bin/python -m mypy agent/python/src
git diff --check
# 모두 통과, mypy 118 source files
```

기본값 24K 검사를 먼저 추가해 기존 32K에서 실패하는 것을 확인하고 수정했다.
16K 입력과 6K 출력 예약은 22K / 24K 문맥에서 모두 검사했다.
기존 native runtime 유닛 테스트의 고정 32K 가상 `/props`와 명령 인자는 선택한 문맥을 따르도록 맞췄다.
v3 실제 평가·40문항 평가·API 모드 평가는 실행하지 않았다.

24K 변경만으로 이번 시스템 상태의 준비 문제는 해결되지 않았다. 추가 조정은 이 실패와 구분해 측정해야 한다.

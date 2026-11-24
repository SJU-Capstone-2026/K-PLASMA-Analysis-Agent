# Qwen 24K / batch·ubatch 256 메모리 검사

날짜: 2026-11-13. M4 Pro / 통합 메모리 24GB의 독립 `v2_localLLM`.

## 결과

사용자 요청대로 Qwen context 24,576을 유지하고 **batch·ubatch만 512/512 → 256/256**으로 줄였다.
전체 스택 검사에서 **추가 swap 0**은 만족했지만 메모리 압력이 정상 `1`에서 warning `2`로 올라가 **실패**했다.
`ready:false`, blocker `LOCAL_MEMORY_EVIDENCE_INVALID`를 실제 확인했다.
사용자의 조건에 따라 **Q01~Q05 웹 접수 0 / API 접수 0**이다. 기존 검사 기준을 완화하지 않았다.

| 항목 | 실제 관측 |
| --- | --- |
| Qwen context / batch / ubatch | 24,576 / 256 / 256 |
| d1 context / batch / ubatch | 32,768 / 16,000 / 16,000, 변경 없음 |
| 계획 의미 Decisions 설정 | 실제 gateway `plan_review_enabled=true` 사전 확인 |
| 짧은 Qwen writer | JSON 정상, 생각 OFF, 4.457초 |
| prompt token | 사전 계산 244 = 실제 사용량 244 |
| memory pressure | 4개 표본에서 `1`, `2` |
| 추가 swap | **0 bytes** |
| 시작 / 최대 resident 지표 | 18.03 / 21.34GiB |
| 측정 전후 instance facts | 동일 |
| d1 실제 추론 / 큰 입력 / 생각 ON planner | 메모리 중단으로 미실행 |

resident는 기존 sampler의 active+wired+compressor 계산값이며 모델 단독 RSS나 완전한 시스템 메모리 분해 값이 아니다.
이전 24K/512 검사는 추가 swap 160.93MiB, 이번은 0이지만 시작 상태가 달라 batch 감소만의 효과로 단정하지 않는다.
짧은 응답 성공과 전체 스택 준비 통과를 구분한다. 이번 실패는 warning에 따른 중단이며 OOM이나 JSON 오류가 아니다.

## 변경과 보존

- `QWEN_RUNTIME_OPTIONS`를 256/256으로 변경했다. 실제 listener 인자 검사도 같은 설정을 사용하고 측정 fingerprint에 반영한다.
- 이전 512 프로필의 메모리 증거는 현재 256 프로필에서 재사용하지 않는다. 실패 측정을 READY 증거로 취급하지 않는다.
- 모델·양자화·엔진·GPU·생각 설정·동시 요청 1·context 24K는 그대로다. d1 프로세스·모델·판단 규칙도 유지했다.
- 전체 입력 16,000, 생각을 포함한 계획 출력 6,000 / 답변 출력 3,000, 호출 90초를 유지했다.
- 메모리 통과 기준은 전 표본 정상·추가 swap 0이며, 요구된 7개 준비 호출 전체를 완료하지 못했다.
- 변경 전 보호 대상 그래프 소스 49개 hash, local 그래프·도구·최종 답변 계약 파일, PlanDraft와 native `submit_plan` 스키마가 변경 전과 동일함을 확인했다.
- 사용자 앱이나 기존 개발 프로세스를 종료하지 않았다. 이번 검사 소유 Qwen 서버와 격리 스택만 정리했고 원래 d1 listener는 유지했다.
- 원시 측정·프로필·비밀값은 Git 밖에 보존했다. 기존 활성 앱 프로필로 승격하지 않았다.

## 실제 검증

native runtime 테스트에서 유효한 256 프로필이 기존 512 정책에 거부되는 실패를 먼저 확인했다.
수정 뒤 256을 수용하고 batch 또는 ubatch만 512로 바꾼 인자, 중복 옵션, 다른 실행 파일은 거부함을 확인했다.

```sh
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m pytest -q \
  agent/python/tests/v2_local_llm agent/python/evals/test_flow_eval.py \
  agent/python/evals/test_v2_harness.py agent/python/tests/test_graph_variants.py \
  agent/python/tests/test_eval_graph_versions.py --tb=short
# 461 passed, 기존 initial_clone marker 경고 3개

node --test scripts/agent/local-llm.test.mjs
# 7 passed

agent/python/.venv/bin/python -m ruff check agent/python/src agent/python/tests agent/python/evals
agent/python/.venv/bin/python -m mypy agent/python/src
git diff --check
# 통과, mypy 118 source files

JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
GRADLE_OPTS=-Dorg.gradle.daemon=false \
node -- scripts/agent/measure-local-llm.mjs --env-file "$KPLASMA_BATCH256_PROFILE"
# exit 2, LOCAL_MEMORY_PRESSURE; 실패 measurement.json 보존
```

모델 파일·서버는 기존 고정 b12317/GGUF를 사용했다. 추가 다운로드·CPU/cloud fallback·실문항 접수는 없다.
d1 교대 실행·장문 안정성·웹 정답률은 이번 검사로 확인하지 못했다.

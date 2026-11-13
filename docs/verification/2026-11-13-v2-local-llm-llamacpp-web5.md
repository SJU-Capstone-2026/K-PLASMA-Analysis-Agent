# llama.cpp 전환·생각 모드 검증 — 전체 스택 준비 실패로 웹 평가 보류

날짜: 2026-11-13. 대상: M4 Pro / 통합 메모리 24GB의 독립 `v2_localLLM`.

## 결과

Qwen 실행·요청 경계는 llama.cpp로 전환했고 실제 native `submit_plan`과 생각 ON 호출을 확인했다.
전체 스택 메모리 준비 검사는 실패했으므로 **연결/운영 검증 완료가 아니다**.
Q01~Q05 웹 평가와 API 평가의 실제 접수는 모두 **0건**이다. 성능 개선율은 산출하지 않는다.

| 계획 단계 | 관측 결과 |
| --- | --- |
| 1. GGUF·native 연결 | 고정 가중치/바이너리 hash 검증. OFF 인공 호출 2개 모두 원래 도구 스키마 통과. 복잡한 계획의 그대로 복사는 실패해 별도 기록. |
| 2. 생각·입력·메모리 | ON에서 동일 복잡한 인공 계획을 정확히 제출하고 분리된 생각 출력과 prompt token 일치를 확인. 전체 스택 메모리 검사는 미통과. |
| 3. 웹 5개 제한 | 행렬·사전 검사·성공/실패/정리 경로 검증 완료. browser 5 / API 0을 선택하며 기본 40+40은 보존. |
| 4. Q01~Q05 실평가 | 준비 실패로 모두 미실행. 이전 1/5 성적과 비교할 새 정답 성적은 없음. |

## 실행 프로필과 보존 범위

- Qwen: `unsloth/Qwen3.5-9B-GGUF:Q4_K_M`, revision `3885219b6810b007914f3a7950a8d1b469d598a5`.
- 파일: `Qwen3.5-9B-Q4_K_M.gguf`, 5,680,522,464 bytes.
- 전체 파일 SHA-256: `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.
- llama.cpp b12317과 동봉 라이브러리 hash를 확인했다. 실행 인자는 Metal `MTL0`, GPU layers `all`, context 32,768, batch/ubatch 512, 동시 요청 1이다.
- 계획 생각 ON / writer OFF, 생각 예산 2,048, 전체 출력 계획 6,000 / writer 3,000, 호출 90초, 입력 16K를 유지했다.
- sample 생성 설정은 계획서의 명시값을 사용했다. MLX와 GGUF의 양자화·실행 환경·sampling도 다르므로 생각 모드만의 효과를 측정한 대조 실험이 아니다.
- 실제 `submit_plan` parameters와 PlanDraft schema가 변경 전과 동일함을 비교했다. local 그래프·도구·최종 답변 계약과 기존 v2/v3 Python 소스도 변경 전 hash/내용을 보존했다.
- 기존 d1 모델·프로세스·검토 규칙은 변경하지 않았다. 이번 메모리 검사는 d1 추론 전 중단되어 새 구성의 실제 Qwen↔d1 전체 교대 실행은 미검증이다.

## 인공 native 호출 결과

| 인공 입력 | 생각 모드 | 결과 | 시간 | 실제 prompt / completion tokens |
| --- | --- | --- | --- | --- |
| 간단한 계획 그대로 제출 | OFF | native 한 호출·스키마·계획 내용 일치·토큰 계산 일치 | 25.661초 | 6,454 / 210 |
| 중첩 참조/계산 계획 그대로 제출 | OFF | native 한 호출과 스키마는 정상. 내용 복사 검사 실패 | 성공 시간으로 집계하지 않음 | 원시 응답은 비공개 보존 |
| 같은 중첩 계획 그대로 제출 | ON | 계획 내용 일치·실제 분리 생각 출력 존재·토큰 계산 일치 | 43.240초 | 6,748 / 803 |

OFF 중첩 계획은 `derive.inputs.values`의 단일 결과 참조를 참조 1개짜리 목록으로 바꿨다.
기존 binder에서 이 차이는 중첩 목록이 되어 계산 입력 오류를 낼 수 있다. `requires.value_type`도 null에서
`quantities`로 바꿨다. 이는 JSON 문법 파손과 다른 계획 내용 변화이며, 정상 스키마만으로 정답을 보장할 수 없음을 보여준다.
이 결과를 숨기지 않고 같은 인공 입력의 요청된 ON 프로필을 추가 확인했다. 실제 평가 문항을 재접수한 것은 아니다.

## 전체 스택 메모리 검사

최초 앱 준비는 기본 Java 24에서 Java 21 toolchain을 찾지 못해 모델 호출 전에 실패했다.
이미 설치된 Homebrew Java 21을 명시해 해결했다. 새로운 JDK나 모델 엔진을 설치해 우회하지 않았다.

첫 실제 인공 스택 시도에서 짧은 writer 호출은 토큰 계산과 일치했지만 이후 메모리 압력이 높아졌다.
작업이 만든 빌드 daemon 2개만 정리하고, daemon을 남기지 않는 Java 21 빌드 설정으로 한 번 재확인했다.
두 번째 실제 측정 결과:

- 짧은 writer: 실제 입력 244토큰 = 사전 계산 244토큰, 5.110초, 생각 출력 없음, JSON 정상.
- 관측 memory pressure 값: `1`, `2`. 정상에서 warning으로 올라갔으며 OOM으로 보고하지 않는다.
- 추가 swap: **675,482,174 bytes = 644.19MiB**. 허용 기준인 추가 swap 0을 만족하지 못했다.
- 샘플 계산상의 최대 resident: **21.38GiB**. 전체 시스템 메모리의 완전한 분해 값이나 모델 단독 RSS가 아니다.
- 측정 전후 실제 모델·실행 프로세스 facts hash는 동일했다.
- 큰 입력·d1·장문 planner 준비 호출은 메모리 상태 때문에 생략했다. 7행 검증 전체가 통과한 것으로 세지 않는다.

원시 실패 보고서는 비공개로 보존했다. 이 실제 실패 증거를 지정했을 때 준비 검사는
`ready:false`, blocker `LOCAL_MEMORY_EVIDENCE_INVALID`를 반환했다. 기준 완화·입력 절단·CPU/cloud fallback으로 통과시키지 않았다.
따라서 이 결과는 현재 시스템 상태와 시작 프로필에서 준비 기준을 만족하지 못했다는 의미이며,
Qwen의 지능 부족이나 24GB 기기의 절대 실행 불가능성을 입증한 결과가 아니다.

## 소프트웨어 검증과 상태

아래 회귀에서 새 기능의 실패 테스트를 먼저 확인했고 수정 후 통과했다.
별도 검토에서 발견한 고정 80회 완료 검사, 실제 생각 수신/토큰 사용량 증거, 측정 전후 프로필 검증,
메모리 압력 시 호출 중단, 실제 listener 실행 파일 hash, 평가 gateway counter 연결도 수정했다.

```sh
# 저장소 루트: 456 passed, 기존 initial_clone marker 경고 3개
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m pytest -q \
  agent/python/tests/v2_local_llm agent/python/evals/test_flow_eval.py \
  agent/python/evals/test_v2_harness.py agent/python/tests/test_graph_variants.py \
  agent/python/tests/test_eval_graph_versions.py --tb=short

# 실행 wrapper: 7 passed
node --test scripts/agent/local-llm.test.mjs

# 통과
agent/python/.venv/bin/python -m ruff check agent/python/src agent/python/tests agent/python/evals
agent/python/.venv/bin/python -m mypy agent/python/src
git diff --check
```

기존 테스트의 MLX alias/포트/생각 OFF 기대와 메모리 fixture는 새 프로필에 맞췄다.
LM Studio load/unload 전용 테스트는 native sleep·잘못된 모델·실제 프로세스 검사로 교체했으며 최초 clone 증거는 재생성하지 않았다.
실제 v3 서버/모델 평가는 하지 않았다.

실험용 Qwen 서버·측정용 backend/UI/DB·이번 빌드 daemon은 정리했다. 기존 d1과 사용자 앱은 유지했다.
기존 활성 private 실행 프로필에는 새 환경을 승격하지 않았다. 새 private 프로필·모델·원시 결과·복구용 변경 전 파일은 로컬에 남겼다.
다음 실평가 전에는 메모리 여유를 확보한 상태에서 같은 준비 검사를 통과해야 한다. 이 기록의 실패 측정을 READY 증거로 사용하면 안 된다.

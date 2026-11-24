# 준비 안정화 수정과 웹 Q01~Q05 검증

날짜: 2026-11-13. M4 Pro / 통합 메모리24GB, 독립 `v2_localLLM`.

## 결과

준비 검사의 native 계약 호출 뒤 안정화 대기를 구현하고, 실제150 Run frozen 평가 환경에서 웹 Q01~Q05를 각1회 실행했다.
**자동 정답5/5, UI 검사5/5, API 모드 접수0**이다. 이전 MLX 프로필의 같은 첫5개 자동 결과는1/5였다.
이번5개는 모두 lookup_search 범주이므로 전체40문항이나 상용v2 동등성으로 확대하지 않는다.
모델 엔진·양자화·생각 설정이 과거와 함께 달라 생각 모드만의 개선 효과라고 부르지 않는다.

| 문항 | 최초 계획 유효성 | 재계획 | d1 계획 검토 | 최종 자동 검사 | UI 검사 | 웹 시나리오 시간 | 수동 확인 |
| --- | --- | ---: | --- | --- | --- | ---: | --- |
| Q01 | 자기 참조로 거부 | 2 | PASS | 통과 | 통과 | 207.9초 | 추가 지적 없음 |
| Q02 | 자기 참조로 거부 | 1 | PASS | 통과 | 통과 | 95.3초 | 추가 지적 없음 |
| Q03 | 자기 참조로 거부 | 1 | PASS | 통과 | 통과 | 118.1초 | 결측 사유 안내 보완 필요 |
| Q04 | 통과 | 0 | PASS | 통과 | 통과 | 79.6초 | 추가 지적 없음 |
| Q05 | 통과 | 0 | PASS | 통과 | 통과 | 84.9초 | 추가 지적 없음 |

최초 계획 통과2/5, 재계획 후 통과3/5다. 실제 문항 재접수는 없고 기존 그래프 내부 재계획만 합계4회 사용했다.
Q01 시간에는 워커 최초 준비와 대기가 포함된다. 위 시간은 브라우저·서버 확인까지 포함한 시나리오 시간이며 순수 추론 속도가 아니다.
각 요청에 d1 PLAN_REVIEW가 실제1회씩 기록됐고 모두 PASS였다. 이번 입력은 d1의 거부·복구 능력을 검증한 사례가 아니다.
답변 해석이 없는 경우 답변 Decisions 검토는 기존 규칙대로 SKIPPED이며 이를 plan review 비활성으로 세지 않는다.

## 준비 판정의 변경

- 처음 native `submit_plan`·writer JSON/SSE·d1 계약을 확인한 뒤, 동일 모델 lease를 보유한 상태에서 최대60초 안정화를 기다린다.
- Qwen과 d1 모두 `/props.is_sleeping`이 실제 bool true이고 메모리 압력이5초 연속 정상이어야 준비를 허용한다.
- warning 또는 깨어난 모델을 관측하면 연속 정상 시간을 초기화한다. critical은 즉시 `LOCAL_MEMORY_CRITICAL`로 실패한다.
- 시간 제한은 sysctl/vm_stat 두 명령과 모델 상태 조회에도 남은 시간으로 전달한다. 잘못된 `/props` JSON은 `LOCAL_MODEL_RUNTIME_UNAVAILABLE`로 실패한다.
- 안정화 성공 뒤에만 계약 검증을 캐시한다. 검증된 워커의 평상시 폴링에는 추가5초 대기를 붙이지 않는다.
- 시작 전·캐시된 폴링의 현재 메모리 압력 검사, artifact·실행 인자·native schema·측정 증거·loopback 경계는 유지한다.

이는 기존 즉시 판정의 동작 변경이며, 메모리 경고를 없애거나 모든 시점의 정상 압력을 보장하는 변경이 아니다.
기존7개 인공 메모리 호출/93개 정상 표본/추가 swap0 증거는 모델·sampling·context·batch 프로필이 같아 그대로 검증했다.
준비 정책·Python 구현 변경은 기존 implementationHash/configFingerprint에 반영돼 최초 native 계약을 다시 확인했다.

## 남은 품질 문제

계획 생성9회 모두 native JSON과 PlanDraft schema를 통과했다. 깨진 JSON이나 adapter 형식 오류는 관측하지 않았다.
하지만 Q01의 처음2개 계획, Q02·Q03의 최초 계획은 조회 단계가 자기 자신의 결과를 선행 조건으로 요구해 기존 validator가 거부했다.
저장한 원시 계획을 같은 validator로 오프라인 재검증해 동일 오류를 재현했다. 문법과 계획 의미·연결의 정확성을 구분한다.

Q01은 결과 서술용 `explain_answer(mode=results)`를 계획에 포함했지만 실제 화면은 기존 결과표였고 물리적 해석 문장은 추가되지 않았다.
모든 문항의 interpretations는0, 예상 밖 사용자 입력은0이었다.

Q03의 사전 `answerReviewRequired` 표시는 frozen oracle override에 있던 조건이다. 원본에 IED width가 없어 정직한 결측을 허용한다.
실제 화면은 가용 값·단위를 유지하고 없는 폭을0이나 추정값으로 만들지 않았지만, `—`만 표시해 원본 결측 사유를 충분히 설명하지 않았다.
따라서 **Q03 자동 통과를 완전한 답변 품질 승인으로 보지 않으며 수동 보완 필요 표시를 유지**한다.
이 경로에는 COMPOSE 호출이 없으므로 이 표시 부족을 Qwen 답변 생성의 잘못이라고 단정하지 않는다. 이번 범위에서 그래프/UI를 수정하지 않았다.

UI 자동 검사는390/800/1008/1440px에서 수행됐다. Q01/Q03 desktop 캡처와 답변·기록을 별도로 확인했다.
수치·원문·화면·DB·원시 모델 응답은 공개 보고서에 포함하지 않고 Git 밖에 보존했다.

## 실행 중 메모리

계측 구간은 격리 스택 준비·native 계약 검사·웹5문항·정리를 포함한 약700.0초다.
- 671개 표본: 정상152, warning519, critical0.
- 추가 swap 약1462.56MiB = 1.43GiB.
- 기존 resident 계산 지표 최대20.51GiB. 모델 단독 RSS나 물리 메모리의 완전한 분해 값이 아니다.
- 가장 긴 관측 warning 구간은 첫·마지막 경고 표본 사이 약128.1초였다.

**메모리 압박 자체는 남아 있다.** 안정화 후 준비 차단을 통과하고 평가를 완료했지만 전체 실행을 정상 압력·스왑0으로 선언하지 않는다.
계측은 시스템 전체이며 다른 앱·가상머신의 활동 영향도 포함한다. 대규모·장시간 운영 안정성을 이5개 결과로 확정하지 않는다.
외부 observer는 critical이면 이번 소유 evaluator에만 interrupt를 보내 취소·정리를 수행하도록 했으며 이번에는 발생하지 않았다.
기존90초 모델 호출 제한·요청 예산·최대 재계획2회·답변 재작성1회는 유지했다.

## 소프트웨어 검증과 보존

```sh
PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m pytest -q \
  agent/python/tests agent/python/evals/test_flow_eval.py agent/python/evals/test_v2_harness.py --tb=short
# 1285 passed, 기존 initial_clone marker 경고3개

node --test scripts/agent/local-llm.test.mjs
# 7 passed

agent/python/.venv/bin/python -m ruff check agent/python/src agent/python/tests agent/python/evals
agent/python/.venv/bin/python -m mypy agent/python/src
# 통과, mypy118 source files

git diff --check
```

warning 회복·재발 초기화·두 모델 sleep·지속 warning60초·critical 즉시 실패·서버 오류·검증 캐시를 테스트했다.
별도 검토의 시간 제한 초과와 malformed JSON blocker 문제는 실패 테스트를 먼저 재현한 뒤 한 차례 수정했고 전체 테스트를 통과했다.
최초 전체 테스트4건 실패는 agent/python 작업 디렉터리에서 상대 fixture 경로를 찾지 못한 실행 실수였으며 저장소 루트 재실행으로 해소했다.

고정 모델 Qwen3.5-9B GGUF Q4_K_M / d1-2B Q8_0, llama.cpp b12317/Metal, context24,576 / Qwen batch·ubatch256,
입력16,000 / 계획 출력6,000 / writer3,000 / 생각 예산2,048을 유지했다.
기존v2/v3 소스49개 hash, local 그래프·도구·답변 계약, PlanDraft/native submit_plan schema와 실제 평가 manifest의 Python source hashes 일치를 확인했다.
LM Studio는 종료 상태를 유지했고 다른 주요 앱과 원래 d1은 유지했다. 이번 소유 Qwen·격리 DB·백엔드·웹만 정리했다.
원래 앱의 활성 private 프로필로 승격하지 않았으며, commit/push/PR은 실행하지 않았다.

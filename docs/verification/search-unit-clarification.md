# v1 순·역방향 단위 정규화와 재질문

2026-10-06 사용자 요청에 따른 수정. `feat/agent-graph-v1`에서 일반 개념 설명 구조와 JS fallback은 변경하지 않는다.

## 원인과 정책

앞선 와트 수정 후 프롬프트는 표기 정규화를 지시했지만, 코드의 단위 검증은 `e볼트`를 eV와 같은 단위로 인정하지 않았다. 순·역방향 엔진은 단위가 없으면 registry 단위를 채웠으며 원문 검증도 단위 생략을 기본 단위와 같은 것으로 인정했다.

- LLM이 순·역방향 모두 명확한 단위 이름·오타를 표준 기호로 정리한다. `e볼트`·`전자 볼트`·`electronvolts`→eV, `밀리토르`→mTorr, `토르`→Torr, 기존 와트 표기·오타→W. 숫자·접두사·배율은 보존하고 수치 환산은 코드가 담당한다.
- 숫자 및 범위에는 사용자가 지정한 단위가 필요하다. 조건·hard constraint·soft target_range에 모두 적용한다. LLM이 기본 단위를 제안해도 원문과 추가 입력에 단위가 없으면 `MISSING_UNIT`으로 조회 전에 멈춘다.
- 숫자 없는 maximize/minimize 정렬은 단위를 묻지 않는다. 내부 계산·저장 scalar와 기존 Run 문맥 규칙은 단위 registry를 계속 사용한다.
- 단위만 답하면 그래프가 기다리던 `unitMetric`에 연결한다. 기존 숫자·범위·연산자·정렬을 유지하며, checkpoint를 재구성한 worker에서도 이어진다. 여러 단위가 누락되면 물리량별로 묻는다.
- 별도 tool 호출도 숫자의 단위 누락을 거부한다. 잘못된 숫자나 단위 크기를 단위 재질문으로 덮어쓰지 않는다. `킬로 와트`·`킬로 전자 볼트` 등의 접두사를 제거하지 않는다.

JSON interpretation schema는 단위 미확정 요청을 담기 위해 optional unit을 유지한다. 공개 pendingInput은 원래 확장 가능한 object이며 단위 질문에 `reason=MISSING_UNIT`, `unitMetric`을 포함한다. 검색 엔진이 반환하는 숫자 조건에는 단위가 확정되어 있다. 기존 `defaultedUnits` 필드는 호환성을 위해 유지하되 새 v1 수치 요청에서는 빈 배열이다.

`graphBuildId=v1-2026-10-06.3`, `promptVersion=interpret-4`. 완료 답변·이전 checkpoint의 계산을 덮어쓰지 않는다. 변경 전 정책으로 대기 중인 요청은 새 질문으로 다시 제출해야 한다.

## 검증

`agent/python/tests/test_search_units.py`에서 수정 전 단위 이름·누락 관련 테스트 **32 failed, 2 passed**를 확인했다. 이후 scalar/범위/0/접두사/단위만 답하기/복수 누락/worker 재구성 회귀를 추가했다. 기존 수치·장애 복구 테스트에는 명시한 단위를 제공하도록 입력 fixture를 갱신해 기존 검증 목적을 유지한다.

실제 `gpt-5.6-luna` / `none`으로 **15/15 시나리오**를 통과했다. `150–160 e볼트`와 단위 생략 후 `e볼트`로 응답하는 역방향을 각각 3회 실행했고, 순방향 단위 생략·왓트 응답, 복수 단위 누락, flux의 배율 질문, 숫자 없는 정렬, 압력·와트 표기도 확인했다. 실행 데이터는 인공 Run 하나만 사용했으며 실제 실험 결과는 사용하지 않았다. 모델 응답 원본은 Git에서 제외한 `.runtime/search-unit-live.json`에만 보관한다.

- `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q`: **292 passed**. 새 단위 회귀는 42개이며, 기존 수치·문맥·저장·장애 복구·설명 테스트도 통과했다.
- `agent/python/.venv/bin/ruff check agent/python/src agent/python/tests agent/python/evals`: PASS.
- `agent/python/.venv/bin/mypy agent/python/src`: **19 source files PASS**.
- `node scripts/verify-public-files.mjs`: **307 files PASS** (신규 파일을 포함한 작업 트리 검사).
- `git diff --check`: PASS.
- 기존 두 로컬 worker를 새 코드로 재시작해 `model=gpt-5.6-luna`, `reasoning=none`, Phoenix `project=K-PLASMA` 준비 로그를 확인했다. UI 코드는 변경하지 않아 화면 폭별 시각 검증은 실행하지 않았다.

변경 범위만 직접 검토했다. 숫자·단위 크기·연산자·정렬의 원문 검증, 단위 질문의 특정 슬롯 연결, 복수 누락 및 checkpoint 복구를 확인했다. 실제 데이터·키·모델 응답 원본을 커밋하지 않는다.

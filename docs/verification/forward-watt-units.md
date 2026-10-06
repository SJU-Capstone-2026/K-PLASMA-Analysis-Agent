# 순방향 조회의 와트 표기 수정

2026-10-06 사용자가 보고한 순방향 실패를 Phoenix의 실제 LLM 응답과 그래프 입력/출력으로 추적했다. 사용자의 요청대로 서브 에이전트 없이 조사·수정·diff 검토를 수행했다.

## 원인과 수정

LLM은 `forward_lookup`, pressure/sourcePower/biasPower의 값과 원문 단위 `와트`를 올바르게 반환했다. 프롬프트가 단위 원문을 보존하도록 지시하므로 이 응답은 지시와 일치한다. 하지만 grounding의 단위 패턴은 `와트`를 인식하지 못했고, 수치 엔진도 이를 `W`와 같은 단위로 받지 않았다. 이 불일치가 `UNGROUNDED_NUMBER`로 처리돼 조회 전에 추가 입력으로 분기했다.

전력 지표에 한해 `와트`, `watt`, `watts`, `w`를 `W`와 같은 단위로 검증·계산한다. 수치와 원문 해석 JSON은 그대로 보존한다. grounding은 한글 접두사가 붙은 와트 단위를 전체로 인식해 킬로/밀리/메가와트를 W로 잘못 승인하지 않는다. 기존 스케일 단위의 지원 범위를 확대하지 않는다.

`graphBuildId=v1-2026-10-06.1`로 수정본을 구분한다. 이전 미완료 checkpoint는 기존의 정확한 버전 일치 정책에 따라 자동 재실행하지 않는다. 완료된 답변과 수치 스냅샷을 재계산하지 않으며 수정은 새 요청에 적용된다. 질문 해석 프롬프트·모델·추론 수준, UI/API/DB 계약은 변경하지 않았다.

## 검증

- 수정 전 새 회귀 테스트에서 단위·grounding·그래프 실패 16건을 확인했다. 접두사 단위 경계의 메가와트 오인도 별도 실패 테스트로 확인한 뒤 수정했다.
- `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q --tb=short`: **219개 통과**. 기존 수치·정렬·checkpoint·관찰 테스트를 포함한다.
- `agent/python/.venv/bin/ruff check agent/python/src agent/python/tests agent/python/evals`: 통과.
- `agent/python/.venv/bin/mypy agent/python/src`: 19개 source file 통과. `git diff --check` 통과.
- 실패한 두 질문의 실제 모델 해석을 같은 저장 manifest에 재생했다. 공백 유무 모두 `EXACT`였고 기존 W 성공 사례와 전체 수치 결과·Run 버전이 일치했다.
- 실제 `gpt-5.6-luna` / `none` 신규 호출 한 건도 `와트`를 유지한 `forward_lookup`을 반환했다. 실제 그래프와 같은 manifest로 조회·결과 검증을 완료했고 W 성공 사례와 결과가 일치했다. OpenAI에는 질문 텍스트만 보내고 Run 자료는 로컬 메모리 backend에서 검증했다. 실제 사용자 DB에 시험 요청을 쓰지는 않았다.
- 재생 도구의 첫 시도는 SDK의 nullable wire JSON을 직접 계약 검증에 넣어 실패했다. 실제 ModelClient가 검증해 저장한 interpretation을 재생하도록 수정했다. 제품의 계약이나 모델 응답을 임의로 보정하지 않았다.
- 실험 payload·사용자 trace·원문 응답은 ignored `.runtime`에만 보관하며 공개 검증 출력과 fixture에는 인공 Run만 사용한다. UI 변경이 없어 이번 수정의 화면 폭 비교는 수행하지 않았다.

## 별도로 확인한 설명 문제

`ConceptId`에는 평균 이온 에너지와 구분된 일반 이온 에너지 항목이 없다. 해당 질문의 최초 해석은 `topics=[meanIonEnergy], aspect=difference`였고, 코드의 두 개념 요구로 입력 대기했다. 이어진 정의 선택에서 모델이 원문에 없는 ionFlux를 추가했지만 현재 개념 검증은 원문 주제 일치를 검사하지 않아 통과했다.

소스 변화 질문은 `topics=[sourcePower, ionFlux, meanIonEnergy, plasma], aspect=relationship`으로 해석됐다. 관계 설명을 정확히 두 개념으로 제한한 결정 코드가 거부했고 후속 입력에서도 같은 네 주제가 유지돼 대기를 반복했다. 이 두 설명 문제는 원인을 확인했으며 이번 순방향 단위 수정에는 포함하지 않았다.

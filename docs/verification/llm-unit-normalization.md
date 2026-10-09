# LLM 단위 표기 정규화

2026-10-06 사용자가 표준 단위 변환과 왓트/왛트/오ㅏ트 같은 오타 처리를 요청했다. 서브 에이전트 없이 수정하고 변경 diff를 단독 검토했다.

## 역할과 경계

이전 프롬프트는 단위 원문까지 복사하게 했고 코드가 같은 표기의 단위만 받아들였다. 이제 LLM이 명확한 단위 표기·오타를 표준 기호로 정리한다. 예를 들어 소스 전력의 `300 오ㅏ트`는 `{value: 300, unit: "W"}`다. 숫자는 원문 그대로 유지하며 kW→W, Torr→mTorr 같은 수치 환산은 코드가 담당한다. 단위 크기가 애매하면 추가 입력을 요청한다. 빠진 숫자나 단위를 채우지 않는다.

코드는 한글 키보드 글자로 분해한 와트 표기의 동일성 또는 한 글자 차이를 검증한다. 단위 전체를 검사해 킬로/밀리/메가 접두사와 다른 단위를 원문의 없는 단위처럼 취급하지 않는다. 와트 오타를 W로 해석해도 숫자 교환·변조, kW/mW/MW/볼트의 W 오인, LLM의 임의 환산은 차단한다. 판단과 계산에서 같은 단위 판별을 사용한다. 새로운 단위 크기의 지원을 추가한 것은 아니다.

`graphBuildId=v1-2026-10-06.2`, `promptVersion=interpret-3`로 식별한다. JSON 계약은 그대로이며 원문 질문은 상태와 Phoenix input에 보존된다. 기존 완료 답변을 다시 계산하지 않고 이전 미완료 checkpoint에 새 해석 정책을 자동 적용하지 않는다.

## 검증

- 회귀 테스트를 먼저 실행해 13개 실패를 확인한 뒤 수정했다. 초기 확장 패턴이 영어 `below`를 단위로 읽는 실패도 기존 평가 harness가 잡았고, 실제 SI 접두사로 한정해 수정했다.
- `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q --tb=short`: **250개 통과**. 네 표기·공백/어순·동일 Run 조회와 기존 수치/정렬/복구/관찰을 포함한다.
- `agent/python/.venv/bin/ruff check agent/python/src agent/python/tests agent/python/evals`: 통과.
- `agent/python/.venv/bin/mypy agent/python/src`: 19개 source file 통과. `git diff --check` 통과.
- 실제 `gpt-5.6-luna` / `none`으로 와트/왓트/왛트/오ㅏ트를 각 3회, 총 **12/12** 실행했다. 모두 unit=W, EXACT이며 이전 W 성공 사례와 전체 결과·Run 버전이 일치했다.
- 별도 실제 호출 2건에서 `0.3 kW`와 `0.008 Torr`의 숫자와 단위를 그대로 보존했다. 임의 환산을 하지 않았다.
- 실제 모델 시험은 질문만 OpenAI에 보내고 저장된 manifest를 로컬 메모리 backend에서 검증했다. 사용자 DB에 시험 대화를 기록하지 않았으며 원문 응답·실험 payload은 ignored `.runtime`에만 보관했다.
- 임의의 모든 오타를 보장하는 평가는 아니다. 비교한 manifest와 같은 그래프의 조회·검증 경로를 시험했으며 이번 수정의 실제 사용자 DB/브라우저 종단 시험은 수행하지 않았다. UI/API/DB 스키마 변경은 없다.

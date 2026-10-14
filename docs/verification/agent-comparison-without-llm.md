# compare_runs 설명 생성 호출 제거

2026-10-14, `fix/remove-comparison-answer`. 선행 PR #14의 비교 그래프 구현 위에서 사용자의 요청에 따라 화면에서 사용하지 않는 비교 설명 생성용 LLM 호출을 제거했다. 질문 해석, 선택 Run 확정, 비교 계산·검증, 수치표·그래프는 유지한다.

## 실행 흐름과 계약

비교는 `select_tool` → 입력·Run 확인 → 필요한 원본 특징값 조회 → `calculate` → `validate_result` → `present`로 완료한다. 설명 생성·검증·설명 재시도는 실행하지 않으며, 계산 결과를 설명 생성용 모델에 전송하지 않는다. 질문 해석용 모델 호출과 일반 질문의 `generate_answer` 흐름은 유지한다.

새 schema 2/3 비교 응답은 `answerSnapshot.answer: null`을 사용한다. Python과 Java에서 null을 허용하되 수치·단위·관찰 출처·정확한 Run 버전 및 참조 목록의 검증은 유지한다. 공개 스키마의 기존 nullable 필드와 프론트의 결과 중심 렌더링을 사용하므로 새 필드나 DB 마이그레이션은 없다. 과거 설명이 포함된 저장 스냅샷은 기존 규칙으로 검증하며 재작성하지 않는다.

기본 graph build는 `v1-2026-10-14.comparison-5`다. 변경된 그래프의 상태·연결과 이전 체크포인트를 섞지 않도록 기존 build fence를 사용한다. backend와 Python worker를 재시작한 뒤 새 질문으로 확인한다. 이전 build의 미완료 요청은 기존 정책에 따라 다시 제출한다. `AGENT_GRAPH_BUILD_ID`를 직접 지정한 환경은 해당 설정도 새 build에 맞춰 갱신해야 한다.

## 검증

인공 데이터와 고정 모델 대역만 사용했다. 실제 모델 API·실험 데이터는 이번 검증에 사용하지 않았다.

- 수정 전 회귀 테스트에서 추가 설명 호출, 설명 모델 실패에 따른 비교 실패, null 설명 계약 거부를 확인했다(8 실패 / 24 통과).
- 비교 선택 추가 입력과 복구에서 질문 해석 1회, 설명 생성 0회를 확인했다. 계산·검증·표시 중 복구해도 선택 버전·0 기준값 비가용 사유·차이값을 유지하며 설명 생성·검증 단계는 실행하지 않는다.
- 설명 모델을 실패하도록 설정해도 비교가 정상 완료된다. 파형 특징값을 사용하는 schema 3 비교도 설명 생성 없이 완료된다.
- Python·Java에서 schema 2/3의 null 설명을 허용하면서 뒤바뀐 Run 참조 목록은 거부한다. 과거 설명 스냅샷과 잘못된 관찰 ID에 대한 기존 계약 검증은 유지한다.
- 프론트는 null 설명이 포함된 저장 비교에서도 수치표·그래프를 표시하며 요약·해석 문구를 표시하지 않는다. 제품 UI 코드는 변경하지 않았다.

| 명령 | 결과 |
| --- | --- |
| `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q --tb=short` | 354 통과 |
| `JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home backend/gradlew -p backend test --console=plain` | 161 통과, 실패·오류·생략 0 |
| `npm test` | Frontend 204, TS Agent 33, 참조 도구 34 통과; 외부 기준 전용 TS Agent 4 생략 |
| `npm run typecheck`, `npm run lint` | 통과 |
| `agent/python/.venv/bin/ruff check agent/python/src agent/python/tests agent/python/evals` | 통과 |
| `agent/python/.venv/bin/mypy agent/python/src` | 오류 없음, 24 source files |
| `npm run verify:public-files`, `git diff --check` | 통과 |

추가로 `mypy --config-file agent/python/pyproject.toml agent/python/src`를 실행하면 `explanations/answers.py`의 `run_groups` 타입 주석 누락과 `graphs/v1.py`의 기존 계산 함수 호출 인수 오류 두 건이 발생한다. 수정 전 HEAD 소스를 별도 임시 경로에서 같은 설정으로 검사해 동일한 두 오류를 확인했다. 이번 변경에서 발생한 오류는 아니며 관련 없는 수정은 포함하지 않았다.

로컬 변경분을 직접 검토했다. 외부 Codex 리뷰 실행은 저장소 변경분의 외부 전송 가능성을 이유로 자동 승인 검토에서 거부되어 수행하지 않았다. 팀원 리뷰를 대체하지 않는다.

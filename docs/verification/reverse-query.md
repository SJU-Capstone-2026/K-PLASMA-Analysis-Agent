# Graph v1 역방향 조건 조회와 탭 변경

2026-10-05 사용자 요청으로 확정한 변경이다. 기존 v1 계획의 독립 목표별 전체 목록과 `현재 정렬` 표시는 이 문서의 동작으로 대체한다. fallback은 별도 버전으로 보존하고 v1 실행에는 사용하지 않는다.

## 조회와 표시

`평균 이온 에너지 150–160 eV, Ion Flux 높은 순`은 에너지 범위 조건으로 먼저 필터링하고, 그 범위를 만족하는 Run을 Flux 내림차순으로 정렬한다. 예를 들어 전체 150 Run 중 범위에 들어오는 Run이 5개라면 공통 결과 5개와 에너지 조건 결과 5개를 표시한다. 전체 Flux 순위 150개를 별도 조회·정렬·저장하거나 탭으로 만들지 않는다. 요청한 일치 결과를 임의로 3개로 제한하지 않는다.

공통 결과는 모든 필수 조건과 정렬에 필요한 값의 가용성을 만족한다. 조건별 결과는 해당 출력 지표의 조건만 만족하는 독립 목록이다. 복수 조건에서 이 목록과 공통 목록이 다를 수 있으므로 기존 구분 안내를 유지한다. 정렬 목표만 있는 질문은 전체 가용 Run이 공통 후보가 되므로 전체 목록을 반환하는 것이 올바르다.

화면 상단에는 검색 조건과 정렬 기준을 표시한다. 중복된 `현재 정렬 … · 결과를 임의로 3개로 줄이지 않습니다.` 문구와 독립 목표 탭을 제거한다. 저장된 이전 v1 답변도 목표 탭을 숨기지만 답변 스냅샷을 변경하거나 수치를 재계산하지 않는다. 기존 목표 탭 선택 상태는 공통 탭으로 표시한다.

## DB와 복구

Python은 LLM 해석을 검증하고 단위를 정규화한 `reverseQuery`를 내부 context API에 보낸다. 서버는 지표·연산자·정렬 방향을 허용 목록으로 다시 검증하고 수치는 바인딩한다. LLM이 SQL을 만들지 않는다. DB는 `WHERE`와 `ORDER BY`로 후보를 가져오며 Python은 동일 후보의 조건과 완전한 수치·동률 순서를 검증한다.

첫 manifest가 성공적으로 저장될 때 현재 Run 버전의 ID 목록을 고정한다. 조건에 해당하는 scalar만 materialize하고 고정된 manifest에 저장한다. 이후 재시도·재시작은 같은 버전과 같은 query를 사용하며 새로 등록된 버전을 끼워 넣지 않는다. 최초 저장 전 트랜잭션이 실패하면 아직 고정된 snapshot이 없으므로 재시도의 성공 시점에 버전을 확정한다. 이때 실패한 조회의 scalar는 반환·계산·checkpoint 저장에 사용하지 않는다. 이어질문에서 기준 Run으로 범위를 만들어야 하면 먼저 ID 목록과 기준 Run scalar만 고정하고, 파생 조건을 만든 뒤 해당 목록 안에서 조회한다.

조건별 탭에 필요한 후보와 누락값·비가용 이유도 보존한다. 공통 결과가 없을 때는 기존의 정확한 근접 후보 규칙을 유지하기 위해 고정된 scalar 목록을 읽는다. 이는 조건 일치 목록을 전체 순위와 교집합으로 만드는 방식이 아니다. Run마다 추가 SQL을 실행하는 N+1 구조도 아니다.

graphBuildId 기본값은 `v1-2026-10-05.4`다. 이전 실행 중 checkpoint는 버전 불일치로 안전하게 종료하며 새 질문으로 다시 실행한다. 완료된 이전 답변은 보존한다.

## 검증

인공 데이터만 사용했다. 정상 범위 조회·정렬 우선순위·strict 경계·단위 변환·0과 누락값·조건별 후보·no-match 근접 후보·버전 고정·checkpoint 재시작을 검증했다. UI는 390 / 800 / 1008 / 1440px에서 탭·상단 chip·넘침·상세 모달·새로고침 복원을 확인했다.

- 테스트를 먼저 변경해 기존 전역 목표 그룹 생성, 미전달 query와 reference-only 옵션의 실패 5건을 확인한 뒤 Python을 수정했다. backend에서도 필터·모드·검증 부재와 극단값 overflow/underflow, 근접 후보 순서의 실패를 확인하고 수정했다.
- `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q`: 177개 통과. Ruff와 Mypy도 통과했다. 역방향 계산 직후 중단을 모사한 checkpoint는 모델·catalog 재호출 없이 복구한다.
- `JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home backend/gradlew -p backend test --console=plain`: 전체 16 suite / 143개, 실패·오류 0건. 신규 DB 검증은 14개이며 기존 요청 영속성 검증 16개와도 함께 통과했다. 마지막 UUID 비교·필요 지표만 변환하는 최적화 이후 전체 suite를 재실행했다.
- `npm test`: frontend 142개, TS agent 33개, 검증 도구 34개 통과. 외부 원본 전용 4개는 명시적으로 skip. `npm run typecheck`, `npm run lint`, `npm run build` 통과.
- `KPLASMA_BROWSER_EXECUTABLE=<local Chromium> npx playwright test --config frontend/src/features/agent/agent-v1.playwright.config.ts --grep 'v1 five cards'`: 인공 UI 4개 폭에서 4/4 통과. 이전 v1 답변에 남은 전역 목표 목록도 숨기며 저장 순서·근접도·후보 참조와 비동기 탭 저장을 보존한다.
- `JAVA_HOME=<Java 21> KPLASMA_BROWSER_EXECUTABLE=<local Chromium> npm run test:e2e`: 독립 인공 DB, 실제 Spring HTTP, Python 그래프, 모델 test double, 브라우저에서 5/5 통과. 네 폭에서 다섯 도구, 추가 입력, reload, 정확한 버전과 중복 turn 방지를 확인했다. 최초 시도는 Java 21 자동 탐색 실패로 빌드 전에 종료했고 설치 경로를 지정한 재실행이 통과했다.
- 재사용·품질·효율 검토: 효율 개선 2개를 반영했다. UUID 기본 키를 문자열로 변환하지 않고 배열 비교하며, query에 필요한 지표만 SQL에서 정규화한다. 테스트 HTTP helper 중복 1건은 공용 fixture 변경으로 범위를 넓힐 이점이 작아 유지했다. 수치·복구 검토에서 발견한 극단값 계산과 근접 후보 동률 순서도 수정·회귀 검증했다.
- 최종 코드 리뷰는 수치·테스트·표준·보안·성능·API·복구 등 9개 관점과 Agent·학습 기록 2개 관점에서 수행했고, 해결되지 않은 actionable finding은 없었다. 독립 외부 모델 리뷰는 인증된 경로가 없어 실행하지 않았다. 직접 조회의 최초 트랜잭션 실패와 snapshot 고정 시점도 검토했으며, 성공적으로 저장한 manifest 이후의 복구 보장을 문서에 명확히 적었다.

이번 변경에서 실제 OpenAI 호출 및 외부 원본 150 Run 비교는 다시 실행하지 않았다. 외부 프로토타입 UI 비교 테스트에는 사용자가 승인한 두 표시 제거만 반영했으며 원본 파일은 수정하지 않았다. 저장된 실제 데이터를 인공 테스트로 대체하거나 검증 산출물을 Git에 넣지 않았다.

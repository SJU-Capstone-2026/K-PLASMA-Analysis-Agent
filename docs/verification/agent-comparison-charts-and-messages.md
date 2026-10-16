# 실험 비교 그래프·독립 채팅 메시지 검증

- 기준 계획: [실험 비교 그래프와 채팅 메시지 개선](../plans/2026-10-09-실험-비교-그래프와-채팅-메시지-개선.md)
- 작업 기준: `feat/agent-graph-v1` (`fdc1d65`) → `feat/agent-comparison-charts`, 2026-10-09. 기존 v1 PR에 의존하는 별도 PR로 분리했으며, 분리 전 검증한 코드와 같은 코드임을 Git diff로 확인했다.
- 사용자의 요청에 따라 단독 구현·검토했다. 독립 리뷰와 팀원 승인을 대체하지 않는다.

## 구현 결과

`compare_runs`는 모든 화면 폭에서 실험 수치표·계산된 차이표를 위에, 요청한 그래프 탭을 아래에 전체 폭으로 표시한다. 2026-10-09 사용자가 승인한 초안과 후속 첨부 화면에 따라 기존 좌우 배치를 변경했다. 번호·실험 이름·수치·상세 열을 분리하고, 제목과 비교 기준은 같은 헤더에 배치한다. 실험 이름은 줄바꿈하지 않고, 수치는 오른쪽으로 정렬한다. 표 안의 공정 조건·버전 펼치기를 제거하고 마지막 열의 `보기` 버튼으로 해당 Run의 정확한 버전 상세를 연다. 기본 실험 행은 약 44px이며 좁은 화면에서는 표 내부만 가로로 스크롤한다. 스칼라와 파형 특징값은 막대, 원본 파형은 선, 2D 출력은 실험별 격자로 표시한다.

상하 배치 검증: `npm run test -w frontend` **203개 통과**, `npm run typecheck`, `npm run lint`, `npm run build -w frontend`, `npm run verify:public-files`, `git diff --check` 통과. `npx playwright test --config frontend/src/features/agent/agent-v1.playwright.config.ts comparison-visualization.pw.ts agent-v1.pw.ts` **8개 통과**. 390/800/1008/1440px 각각에서 표 다음에 같은 폭의 그래프가 배치됨, 실험 이름 줄바꿈 없음, 기본 행 높이 46px 이하, 정확한 버전의 상세 보기와 모달 닫기, 화면 넘침 없음, 그래프 전환·실험 표시·복원 및 기존 조회 화면을 확인했다. 삭제한 메타데이터 펼치기 검증은 상세 버튼의 버전·동작 검증으로 대체했다. UI만 변경해 Python·backend 테스트는 이번에 재실행하지 않았다.

같은 날 축 글자 잘림·단위 겹침을 수정했다. 고정된 SVG 왼쪽 여백에서 큰 음수 축 라벨이 경계 밖으로 나오는 현상을 인공 데이터로 재현했다. 축 글자 길이에 따라 여백을 정하고 축·선·막대·격자·극값 표식을 같은 좌표계에 배치한다. 절댓값이 10⁶ 이상이거나 0보다 크고 0.01 미만인 값은 그래프에서 지수 표기로 줄이며 원값은 툴팁에 남긴다. 막대 간격도 값 라벨 길이를 반영한다. 파형·막대의 세로 단위 중복 표기를 제거하고 상단 단위는 줄바꿈할 수 있게 했다. 격자의 y축 단위는 숫자와 떨어진 위쪽에 가로로 표시한다. 원본 값·단위·계산·저장 계약은 변경하지 않았다.

개별 Run·전체 후보의 `채팅에 추가` 동작에서는 저장 후 입력창에 강제로 포커스를 주던 코드를 제거했다. 현재 위치·클릭한 버튼의 포커스를 유지하고 기존 오른쪽 아래 알림만 표시하며 3,200ms 뒤 자동 제거한다. 다중 참조 누적·중복 제거·저장 완료 후 알림·질문 전송 대기 정책은 유지한다.

축·참조 추가 검증: frontend **203개**, `npx playwright test --config frontend/src/features/agent/agent-v1.playwright.config.ts comparison-visualization.pw.ts chat-references.pw.ts` **8개 통과**, 타입 검사·lint·frontend build·공개 파일 검사·diff 검사 통과. 네 화면 폭에서 큰 양수·음수·10⁻⁹ 단위의 작은 값, 선·막대·격자의 모든 SVG 글자 경계 및 서로 겹치지 않음, 12개 실험의 막대 간격을 확인했다. 실제 클릭 이벤트 시점부터 참조 저장 후까지 문서 스크롤·포커스 유지와 알림 자동 제거도 확인했다. 자동화 도구가 클릭 대상을 화면 안으로 가져오는 과정의 스크롤은 앱 동작 측정에서 제외했다. 인공 데이터만 사용했고 Python·backend 테스트는 이번 UI 수정에서 재실행하지 않았다.

2026-10-09 사용자 요청으로 비교 출력의 `계산 정의·원본`, `계산 근거`, `가능한 해석`, `설명의 한계` 영역과 전용 스타일·설명 전달값을 제거했다. 삭제한 근거 펼치기 기능의 UI 테스트 두 개를 삭제하고, 기존 저장 답변·그래프 테스트에서 설명 영역이 없는 출력을 확인한다. 계산 결과·비가용 이유와 내부 근거 검증, 저장 답변의 데이터 계약은 유지한다.

출력 정리 검증: `npm run test -w frontend` 203개 통과, `npm run typecheck`, `npm run lint`, `npm run build -w frontend`, `npm run verify:public-files`, `git diff --check` 통과. `npx playwright test --config frontend/src/features/agent/agent-v1.playwright.config.ts comparison-visualization.pw.ts`는 390/800/1008/1440px 네 경우에서 설명 영역 제거, 수치·파형·2D 그래프, 실험별 표시 전환과 접기·복원을 확인했다. 이번 변경에서 Python·backend 테스트는 재실행하지 않았다.

처음에는 모든 비교 실험을 표시한다. 지표 탭, 실험별 표시 전환, 전체 표시·숨김, 그래프 접기는 브라우저에서 즉시 처리하고 turn별로 저장한다. 이 조작은 비교 대상·계산·LLM 설명을 바꾸지 않는다. Run 태그·표·막대·선·범례가 기존 색상 매핑을 공유한다. 같은 Run의 다른 버전은 같은 색과 추가 버전 라벨·선 모양으로 구분한다.

질문 전송 직후 사용자 메시지와 당시 실험 태그를 별도로 표시한다. 서버의 기존 요청 저장값에서 원래 질문·첨부 목록을 투영하므로 HITL에서 선택한 실험이나 완료 답변이 원래 첨부 목록을 덮어쓰지 않는다. 전송 전에 동기 예약을 잡아 중복 클릭을 막고, 응답 수락이 불명확하면 같은 요청 키와 본문으로 재확인한다. 전송되지 않은 브라우저 outbox와 수락 여부가 불명확한 요청을 구분한다.

## 수치·원본 계약

- 네 native 도구를 유지한다. `compare_runs`에 허용 목록의 `comparison_fields`와 `plot_ids`를 추가했다. 원본이 필요할 때만 LangGraph의 `load_comparison_outputs` 노드가 실행된다.
- IED·IAD·IEAD·RF 전류 밀도·전극 전위·쉬스 이온 밀도·수렴 잔차 7종을 지원한다. 특징값은 표시용 축소 배열 대신 전체 원본에서 추출한다. 표시에는 실제 원본 지점과 원본 극값 위치를 사용한다.
- 피크는 최대 y값, 첨두간 값은 최대−최소, 반첨두간 진폭은 그 절반이다. IED 폭은 기존 P90−P10을 유지한다. 단일 점의 진폭은 자료 부족이며, 공동 극값은 개수와 첫 원본 위치를 보존한다. 좌표·위상·각도에 변화율을 붙이지 않는다.
- 전류 밀도 `statampere/cm²`, 거리 `cm` 등 원본 단위를 유지한다. IEAD·밀도처럼 강도의 물리 단위를 확인할 수 없는 출력은 단위를 만들어 붙이지 않는다. 원본 격자는 표시할 수 있지만 단위가 필요한 강도 수치 비교는 비가용으로 처리한다.
- RMS·절댓값 피크·위상차 등 미등록 계산은 다른 특징값으로 대신 답하지 않고 지원 범위를 확인한다. LLM은 코드가 만든 관찰 ID와 정의를 사용하며 실험 숫자를 자유 문장에서 다시 계산하지 않는다.
- 확장 비교는 schema 3, 검색·일반 답변은 schema 2다. 과거 schema 1/2는 읽기 호환하며 새 계산으로 덮어쓰지 않는다. 생산자 Python·Java, 소비자 TypeScript와 공유 인공 fixture·API 문서를 함께 갱신했다.
- 원본 배열은 browser 전용 출력 응답에만 포함한다. worker 응답·체크포인트·저장 답변·모델 입력에는 원본 배열을 넣지 않는다. 모델용 근거는 최대 80개 관찰과 60,000자 예산으로 줄이고 저장된 전체 수치표는 유지한다. 많은 실험의 개별 설명 요구는 범위를 확인한다.

## 조회·캐시·계측

`POST /api/run-versions/outputs`는 정확한 Run 버전 최대 50개와 출력 ID 최대 7개를 받는다. 프론트와 worker는 25개씩 분할한다. 한 batch에서 원본 manifest SQL 한 번으로 버전·파일을 가져오며 Run별 상세 조회를 반복하지 않는다. 내부 API는 고정된 비교 참조 및 worker claim/revision을 I/O 전후로 검사한다.

서버는 버전·원본 식별자·출력·특징값 정책별 최대 512개 LRU를 사용한다. cold 추출은 파일 hash 확인 후 전체 파싱하므로 물리 파일 읽기가 한 번이라고 주장하지 않는다. 원본 저장소는 불변으로 관리하며 cache hit에서는 파일 존재와 DB 버전을 다시 확인하고 파일 내용 hash를 매번 다시 계산하지 않는다. 삭제 버전·없는 원본·무결성 불일치·비정상 원본은 개별 비가용으로 표시한다.

브라우저는 최대 256개 출력 캐시와 동일 조회의 진행 중 Promise를 공유한다. 화면에 가까워졌을 때 활성 원본 탭만 조회한다. 스칼라만 요청하면 원본 조회는 0회다. 저장 답변의 버전·출력·원본 식별자·축/값 단위와 조회 결과가 다르면 해당 그래프를 차단하고 과거 수치·설명은 보존한다. 특징값 정책 변경만으로 원본 표시를 막지는 않으며 새 정책으로 과거 특징값을 재계산하지 않는다.

- 서버 DEBUG 로그: `comparison outputs: runs=... outputs=... manifestQueries=1 cacheHits=... extractions=... durationMs=...`.
- Phoenix의 `load_comparison_outputs` 노드: 선택 Run 수, 출력 수, 원본 샘플 수, 비가용 출력 수, compact payload bytes, 기존 노드 지연을 기록한다.
- 2/5/150 Run의 원본 manifest 조회는 batch 25 기준 **1/1/6회**였다. 기존 비교 context 준비는 identity+scalar **2회**, manifest 재사용은 identity **1회**다. 서로 다른 경로의 쿼리 수를 섞어 세지 않는다.

## 검증 결과

인공 데이터만 사용했다. 실제 실험 결과·사용자 대화·키·trace·스크린샷은 공개 저장소에 포함하지 않는다.

| 명령/검증 | 결과 |
| --- | --- |
| `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q` | **349 통과** |
| `JAVA_HOME=… ./gradlew test` (`backend/`) | **159 통과**, 실패·생략 0 |
| `npm test` | Frontend **204**, TS Agent **33**, 참조 도구 **34** 통과. 외부 기준 전용 TS Agent 4건 생략 |
| `npm run typecheck`, `npm run lint`, `npm run build` | 통과 |
| Python Ruff / Mypy | 통과 / 24개 source file 오류 없음 |
| `playwright test --config frontend/src/features/agent/agent-v1.playwright.config.ts` | **16 통과 / 외부 프로토타입 전용 8 생략** |
| `KPLASMA_V1_LIVE_WIDTHS=1440 npm run test:e2e` | 실제 HTTP·PostgreSQL·Python graph와 고정 모델 대역: **2 통과** |
| `KPLASMA_V1_LIVE_WIDTHS=1440 npm run test:e2e:live` | 실제 모델·HTTP·DB·worker·브라우저: **2 통과**. 네 도구, 비교 선택, 추가 입력·reload·모달·중복 방지 확인 |
| 실제 `gpt-5.6-luna` / 추론 `none` | 후보 전체 조회 → 태그 3개 잔차 파형·마지막/최대 비교 → 플럭스 비교 **3/3 완료** |
| `npm run verify:public-files`, `git diff --check` | 통과; heuristic guard와 변경 파일 수동 검토 병행 |

브라우저에서는 **390/800/1008/1440px**에서 5개 인공 실험의 선·막대·격자 탭, 개별/전체 표시, 접기 후 reload, 즉시 질문·원래 태그 표시, 연속 제출 시 요청 한 건, 가로 넘침·page 오류 없음을 확인했다. 1440/390px 캡처를 직접 확인해 요청 수치가 표 앞쪽에 배치되고 격자 셀이 정상 면적으로 표시됨을 검토했다.

원본 추출 테스트는 표시점 사이의 원본 피크, 공동 최대, 음수·0·단일 점, 전체 구간 진폭, 원본 단위, 2D 좌표와 단위 미지정, residual 절댓값 최대·마지막 반복을 검증한다. 계약 테스트는 schema 2의 엄격함과 schema 3 확장·좌표 변화율 금지·정확한 버전·원본 배열 제외를 검증한다. 전송 테스트는 수락 응답 유실, 동일 키/본문 재시도, 원래 질문·첨부 보존과 중복 방지를 검증한다.

실제 모델 시험에서 Phoenix `project=K-PLASMA` 초기화 로그를 확인했다. 이번 검증에서 원격 UI의 span 수·본문을 따로 대조하지 않았다. 단발 실제 모델 시험과 캐시 사용 API 확인은 동작 확인이며 cold/warm 성능 비교·개선율·처리량 측정이 아니다. 실제 150 Run 원본의 동시 부하·최대 DOM 비용은 측정하지 않았다.

## 요구사항 대조·적용

R1–R2/R13은 요청 메시지 투영·전송 예약·outbox와 채팅 검증, R3–R9는 비교 UI·공유 색상·7종 출력 탭과 네 폭 검증, R10–R12는 원본 특징값·단위·비가용·근거 검증, R14는 compact 경계·batch·캐시·모델 예산 및 SQL 계측으로 확인했다. 계획의 테스트 파일 제안은 기존 통합 테스트와 새 `ComparisonFeatureExtractorTest`, `test_comparison_fields.py`, `comparison-visualization.pw.ts` 등에 합쳐 중복 테스트 파일을 만들지 않았다.

새 backend·worker·frontend를 재시작해야 적용된다. 최초 그래프 검증의 build는 `v1-2026-10-09.comparison-3`, tool prompt는 `tool-selection-3`, explanation prompt는 `comparison-answer-2`였다. 이후 [비교 설명 근거 오류·재시도 수정](agent-comparison-explanation-evidence.md)으로 build `comparison-4`, explanation prompt `comparison-answer-3`, 근거 정책 `observations-2`를 적용했다. DB 마이그레이션은 없다. 이전 미완료 요청은 기존 build fence 정책에 따라 새 질문으로 제출한다. 새 batch 복구·서버 장애 복구 체계는 추가하지 않았으며 단일 Run 후속 라우팅과 RAG는 후속 범위다.

반영 후 담당자는 첫 30분 동안 스칼라·파형·2D 비교, 3개 이상 태그 전송, 표시 전환/reload를 확인한다. 정상 신호는 정확 버전·단위, 질문/완료 답변 각 한 건, 스칼라의 원본 조회 0회, 표시 전환의 LLM 호출 0회다. `SOURCE_MISMATCH`, `SOURCE_INTEGRITY_MISMATCH`, 지속적인 `ANSWER_*` 실패나 중복 요청이 발생하면 해당 출력과 claim/revision·원본 메타데이터를 확인하고 이번 backend·worker·frontend 배포를 함께 되돌린다. fallback 자동 전환은 하지 않는다.

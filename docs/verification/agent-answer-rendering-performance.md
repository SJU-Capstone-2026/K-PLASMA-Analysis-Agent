# 답변 렌더링과 검색 표시 데이터 재사용의 성능 검증

2026-10-08. `feat/agent-graph-v1`, PR #12의 후속 변경이다. 앞선 카드·그래프 탭 즉시 표시 이후 관찰한 저장 요청 시작 지연을 줄인다. [이전 측정 기록](agent-optimistic-turn-ui.md)과 [조건 결과 탭 개선](candidate-tab-save.md)은 별도 단계의 기록으로 보존한다.

## 문제 발견 → 원인 → 해결 방식 → 결과

### 변경 없는 답변의 재렌더링

- 문제 발견: 카드 하나의 선택과 상세 그래프 탭 변경에도 저장 요청 시작 전 약49ms가 걸렸다. 질문 입력창에 입력할 때도 기존 답변을 다시 그렸다.
- 원인: `App → AgentPage → 모든 AnswerView`로 렌더링이 전파됐다. 실제 20 turn workspace의 개발 StrictMode 계측에서 한 클릭당 답변 함수가 총40번 실행됐다. 상태 갱신 자체는 약0.1ms였지만 전체 렌더링이 직렬 저장 큐의 Promise callback 실행을 늦췄다. 앞선 저장 요청의 I/O를 기다리는 상황은 아니었다.
- 해결 방식: turn별 행을 `memo`로 감싸 변경되지 않은 turn을 재렌더링하지 않는다. 안정된 action dispatcher는 layout commit 후 갱신한 현재 turn과 callback을 읽는다. 오래된 콜백을 무시하는 비교 함수를 쓰거나 과거 Run 참조를 고정하지 않는다.
- 결과: 제품 적용 전 독립 대조에서 클릭→fetch 호출 중앙값은 카드47.5→23.3ms, 그래프48.1→25.3ms였다(각20회, 경계 계측 포함). 이 대조와 아래 제품 최종40회 측정은 서로 합산하지 않는다. 제품에서는 표시 모델 재사용도 함께 적용했다.

### 같은 검색 답변의 표시 데이터 재생성

- 문제 발견: 변경된 검색 답변만 렌더링한 대조에서도 약24ms의 저장 시작 대기가 남았다.
- 원인: `v1SearchModel`이 UI만 바뀌어도 저장된 전체 후보 그룹과 수치·단위 표시 문자열을 다시 준비했다. 해당 구간은 계측 중앙값 카드18.8ms, 그래프19.2ms였다.
- 해결 방식: 검색 답변 컴포넌트 안에서 `answerSnapshot`과 `question`을 의존성으로 `useMemo`를 사용한다. 선택 카드·조건 탭 값은 캐시 밖에서 계속 현재 UI로 렌더링한다. 새 답변·질문 변경은 재계산하고 대화 제거/컴포넌트 해제는 캐시를 폐기한다. 저장 Run 버전·Python 계산 결과·정렬·근접도는 다시 계산하지 않는다.
- 결과: 제품 적용 전 추가 대조의 클릭→fetch 호출은 카드4.6ms, 그래프5.8ms였다. 제품 최종 측정 결과는 아래와 같다. 두 개선의 제품 개별 효과를 분리 측정한 것으로 주장하지 않는다.

## 제품 코드 적용 후 실제 서버·DB 전후 측정

### 환경과 방법

- 기준: `2b12c186d13dabfa9600c4d20cb73d2b59dcc833`의 제품 코드와 이번 적용 코드.
- 동일 Chromium **153.0.8010.12**, Vite 개발 서버/StrictMode, **1440×1000px**.
- 이미 실행 중인 backend **8080**, PostgreSQL **15432**, 등록 Run **150개**, 저장 turn **20개**, 기존 공통 후보 **11개** 화면. 150개 카드 동시 표시 시험은 아니다.
- **응답 mock·고정 지연·네트워크 throttling·진단용 Profiler/시간 마커 없음**. 실제 브라우저 클릭과 ResourceTiming/MutationObserver를 사용한다.
- 전→후→후→전(ABBA), 실행마다 동작별 워밍업5회 제외 후20회. 전후 각각 **40개 표본/동작**, nearest-rank 중앙값/p95(20번째/38번째 표본).
- baseline plugin은 `useConversation`, `AgentPage`, `V1AnswerView`, `v1-search-model` 네 파일을 위 Git ref의 소스로 대체한다. hook만 교체해서 이번 컴포넌트 개선을 수정 전으로 잘못 측정하지 않는다. 다른 소스와 API/DB는 동일하다.
- 각 실행의 이전 저장 응답 반영을 기다린 뒤 다음 클릭을 측정한다. 실행당 UI PATCH50회와 별도 복원 PATCH1회. 전후 각각 클릭/저장100회, 네 실행의 복원 총4회. 측정 중 빌드/다른 테스트를 동시에 실행하지 않았다.

### 실제 결과

| 동작 / 측정 지점 | 전 중앙값 | 후 중앙값 | 전 p95 | 후 p95 |
| --- | ---: | ---: | ---: | ---: |
| 카드 선택·해제 / DOM 변경 | **48.1ms** | **4.5ms** | 93.6ms | 18.3ms |
| 저장된 그래프 탭 / DOM 변경 | **49.3ms** | **5.4ms** | 94.6ms | 21.3ms |
| 카드 / 두 번째 animation frame까지 | 49.7ms | 31.7ms | 95.2ms | 32.3ms |
| 그래프 / 두 번째 animation frame까지 | 51.0ms | 41.8ms | 96.3ms | 45.8ms |
| 카드 / 클릭→fetch 시작 | **48.2ms** | **4.6ms** | 93.7ms | 18.4ms |
| 그래프 / 클릭→fetch 시작 | **49.4ms** | **5.5ms** | 94.7ms | 21.3ms |
| 카드 / 클릭→응답 본문 수신 완료 | 102.0ms | 59.6ms | 142.1ms | 73.4ms |
| 그래프 / 클릭→응답 본문 수신 완료 | 97.9ms | 53.1ms | 136.5ms | 74.5ms |
| 카드 / HTTP 시작→본문 수신 완료 | 51.8ms | 52.1ms | 56.8ms | 57.7ms |
| 그래프 / HTTP 시작→본문 수신 완료 | 48.2ms | 46.1ms | 54.9ms | 69.2ms |

DOM 중앙값은 카드 **90.6%**, 그래프 **89.0%** 감소했다. 두 번째 frame 근사값 감소는 각각 **36.2% / 18.0%**다. 클릭→응답 감소는 **41.6% / 45.8%**로, 요청 시작 대기를 줄인 효과가 포함된다. HTTP 자체는 카드 중앙값과 그래프 p95가 오히려 늘었으므로 서버·DB가 빨라진 것으로 주장하지 않는다.

DOM은 click 이벤트 capture→선택 class/aria-selected의 MutationObserver 확인이다. 두 번째 frame은 이후 두 번의 requestAnimationFrame까지로 화면 반영 기회의 근사값이며 실제 픽셀 표시 완료·공식 INP·140ms 테두리 애니메이션 종료가 아니다. HTTP는 브라우저 ResourceTiming(fetch 시작→본문 수신 완료)으로 proxy/backend/DB/전송이 포함되고 JSON 파싱·서버 확정 후 렌더링은 포함되지 않는다. fetch 시작 지연은 표본별 `clickToResponseMs - httpMs`에서 계산한다.

카드 응답 본문 중앙값 **816,332 bytes**, 그래프 **816,343 bytes**로 전후 동일하다(선택·탭 문자열 길이의 차이). 요청 수·응답 크기·DB 쿼리 수를 줄인 변경은 아니다. 실제 DB 쿼리 수/실행 시간은 별도로 측정하지 않았다.

실제 HTTP/DB 실행 **4/4** 통과, UI 저장 오류/page 오류 **0건**. 각 실행 종료 시 모든 turn의 UI가 시작 상태로 복원됐고 대화·답변 스냅샷 불변을 확인했다. 실제 질문·실험 수치·식별자·payload·화면·trace는 게시하지 않는다. 측정 JSON과 집계는 Git 제외 경로 `agent/python/.runtime/turn-ui-render-perf/`에만 보관했다.

## 회귀 검증과 검토

- 새 테스트는 입력창 입력의 불필요한 재계산을 수정 전에 실패로 재현했다. 실제 표시 함수의 실행을 관찰하며 함수/답변 컴포넌트를 대체하지 않는다. UI 변경 뒤 선택 표시, 최신 handler/후보 그룹 참조, 새 답변의 정확한 Run 버전, 질문 변경의 안내 갱신, 대화 제거 후 캐시 폐기를 검증한다.
- `npm test`: Frontend **188**, TS Agent **33**, 참조 검증 도구 **34** 통과. 외부 원본 전용 **4**건 명시 skip.
- `npm run typecheck`(e2e 포함), `npm run lint`, `npm run build`, `npm run verify:public-files`, `git diff --check`: 통과.
- `cd frontend && npx playwright test --config src/features/agent/agent-v1.playwright.config.ts agent-v1.pw.ts`: **4/4** 통과, **390/800/1008/1440px**. 응답 전 카드·조건 탭·그래프 탭 변경, 빠른 연속 클릭, 저장 후 reload, 키보드·모달·가로 넘침을 확인했다. 390/1440px 인공 데이터 화면도 직접 확인했다. 기존 markup/CSS/수치/정렬은 유지한다.
- 기존 저장 거절·응답 유실·첫 탭 실패·새 대화/초기화·선택 직후 질문의 회귀 테스트도 통과했다.
- `ce-simplify-code`의 재사용·명료성·효율과 `ce-code-review`의 정확성·캐시 수명·최신 callback·저장 경쟁·검증 충실성 관점을 요청대로 단독 검토했다. 적용이 필요한 구체적 결함은 발견하지 않았다. 서브 에이전트/독립 교차 모델 리뷰는 수행하지 않았으며 팀원 승인은 별도다.
- Python/backend 테스트·실제 모델 호출·부하 테스트는 이번 프론트 변경의 로컬 검증에서 재실행하지 않았다. 실제 서버/DB 클릭 시험과 구분한다.

## 재현

backend/PostgreSQL과 기존 역방향 공통 후보의 **이미 저장된 그래프 탭**이 필요하다. 새 대화나 Run을 만들지 않는다. 해당 workspace를 다른 화면에서 조작하지 않는 동안 실행한다. 종료 시 두 UI 필드만 복원하고 다른 최신 선택/epoch가 감지되면 덮어쓰지 않고 실패한다. 정상 저장만큼 workspace revision은 증가한다.

```sh
cd frontend
mkdir -p ../agent/python/.runtime/turn-ui-render-perf
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_BASELINE_REF=2b12c186d13dabfa9600c4d20cb73d2b59dcc833 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-render-perf/before-1.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-render-perf/after-1.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-render-perf/after-2.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_BASELINE_REF=2b12c186d13dabfa9600c4d20cb73d2b59dcc833 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-render-perf/before-2.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
```

실측 모드는 인공500ms 시험을 명시 skip한다. baseline ref가 없으면 현재 제품 소스를 사용한다. 이전 hook-only 비교용 `KPLASMA_UI_BASELINE_FILE`과 ref를 동시에 지정하면 오류로 종료한다. 5198 포트가 필요하며 일반 개발/빌드는 이 시험 설정을 사용하지 않는다.

## 한계와 반영 후 확인

단일 사용자·로컬 개발 환경의 순차 클릭 시험이다. 운영 INP·LLM 생성·페이지 초기 로딩·처리량·다중 사용자 부하의 개선을 입증하지 않는다. 새 전체 workspace 응답은 새 객체로 읽혀 확정 후의 답변 렌더링/캐시 재생성이 남는다. 큰 응답 파싱·응답 축소·저장 병합은 후속 범위다. 저장 확인 전에 페이지를 닫으면 마지막 선택이 유실될 수 있고 질문 전송은 저장 확인을 기다린다.

운영 담당자가 반영 후 첫30분 동안 마지막 클릭 유지, 새 답변/Run 버전 갱신, 실패 안내, reload 복원, 질문 참조의 일치를 확인한다. Network의 `/api/workspace/turns/*/ui`는 클릭당 한 건이며 새 저장 실패/반복 요청이 없는 것이 정상 신호다. 최신 수치·버전이 갱신되지 않거나 잘못된 Run으로 연결되면 이번 프론트 변경을 되돌리고 snapshot/epoch와 callback을 확인한다. API/DB 변경이 없어 기존 프론트로 되돌릴 수 있다.

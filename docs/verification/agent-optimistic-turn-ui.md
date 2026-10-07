# 후보 카드·상세 그래프 탭의 즉시 표시 검증

- 날짜: 2026-10-08
- 비교 기준: `d26f6e7c421bd52d56871a7ed445f2993862ead2`
- 반영 브랜치: `feat/agent-graph-v1`, PR #12
- 범위: 프론트엔드 화면 선택 상태와 질문 전송 전 선택 확인. 수치 엔진·물리 단위·Python 그래프·API 계약·DB 스키마는 변경하지 않음.

## 동작

`useConversation`은 서버가 확정한 workspace/revision과 화면 표시용 대기 패치를 구분한다. 기존 조건 결과 탭에 더해 후보 카드 선택·해제, 대화 내 상세 그래프 탭을 클릭 시 표시한다. 저장은 기존 직렬 큐에서 최신 서버 revision으로 수행한다.

대기 패치는 turn별 순서 목록으로 관리한다. 이전 저장 응답은 자기 패치만 제거하므로 이후 클릭 및 다른 필드의 선택을 덮어쓰지 않는다. 상세 탭 맵은 Run별로 합쳐 다른 Run의 탭을 보존한다. 새 대화/초기화/삭제/다른 epoch는 이전 표시 패치를 폐기한다.

저장 거절 시 서버 상태를 다시 읽어 복원한다. 저장은 성공했으나 응답이 유실된 경우도 같은 경로로 실제 저장값을 확인한다. 추가 조회가 불가능하면 마지막 서버 확정값을 표시하고 오류를 안내한다. 첫 상세 탭 저장 실패 시 기본 탭이 남도록 대화 상세 모달은 항상 제어된 tab 값(미선택은 빈 문자열)을 넘긴다.

질문 전송 시 화면에 표시된 선택의 정확한 Run 버전을 기록하고 저장 큐 완료 후 확정값과 비교한다. 선택 또는 해제가 반영되지 않았으면 질문을 중단하여 예전 Run이나 무참조 질문으로 실행되지 않도록 한다.

실험 기준·후보 전체 참조, 실제 조회/계산, 기록 저장·삭제는 서버에서 확정한다. 표시 개선은 `activeCandidateGroup`, `selectedCandidateRunId`, `runDetailTabs`로 한정한다.

## 실제 서버·DB 성능 측정

앞서 제시한 500ms 고정 지연 수치는 인공 응답 시험이었다. 아래 수치를 **실제 로컬 측정의 대표 결과**로 사용한다. 고정 지연 시험의 약 97% 개선율을 실제 서비스 개선율로 해석하지 않는다.

### 환경과 비교 방법

- 로컬 Chromium **153.0.8010.12**, Vite 개발 서버, **1440×1000px**.
- 이미 실행 중인 실제 backend **8080** 및 PostgreSQL **15432** 사용. HTTP 응답 mock·강제 지연·네트워크 throttling 없음.
- 실제 등록 Run **150개**, 저장된 대화 **20개**. 그중 기존 역방향 답변의 공통 후보 **11개** 화면에서 카드 선택·해제와 이미 저장된 상세 그래프 탭을 측정. Run 150개를 동시에 카드로 렌더링한 시험은 아니다.
- 수정 전은 `d26f6e7c421bd52d56871a7ed445f2993862ead2`, 수정 후는 `44899b5f638ed8e2c54e7577686c0e7d3e6d4c55`의 hook. baseline Vite plugin으로 hook 하나만 교체하며 다른 앱 코드·backend·DB·브라우저 조건은 동일하다.
- **전 → 후 → 후 → 전** 순서로 4회 실행. 각 실행에서 동작별 워밍업 **5회** 제외 후 **20회** 기록. 전후 각각 **40개 표본/동작**으로 집계했다. 클릭은 직렬로 진행하고 다음 클릭 전에 이전 저장 응답의 화면 반영을 기다렸다.
- 전후 각각 워밍업 포함 **100회 클릭 / 실제 UI PATCH 100회**. 각 실행 종료 후 두 UI 필드만 원래 값으로 복원하는 별도 PATCH 1회, 총 **4회**. 대화·질문·답변·Run 수치는 생성하거나 변경하지 않았다.

DOM 시간은 실제 브라우저 click 이벤트 capture부터 선택 class/aria-selected의 MutationObserver 확인까지다. frame 시간은 이후 두 번째 requestAnimationFrame까지이며 화면 반영 기회를 지난 근사값이다. **실제 픽셀 표시 완료 시점·공식 INP·140ms 카드 테두리 애니메이션 완료 시간은 아니다.** 중앙값과 p95는 nearest-rank 방식이며 40개 중 각각 20번째·38번째 값이다.

HTTP 시간은 브라우저 ResourceTiming의 실제 fetch 시작부터 응답 본문 수신 완료까지다. Vite proxy·backend·DB·본문 전송이 포함되며 DB 실행 시간만 따로 분리한 값은 아니다. 클릭 → 응답은 클릭부터 그 응답 수신 완료까지로, fetch 시작 전 대기도 포함한다. 리소스 시간은 애플리케이션의 JSON 파싱과 저장 확인 후 렌더링을 포함하지 않는다.

### 실제 결과

| 동작 / 측정 지점 | 전 중앙값 | 후 중앙값 | 중앙값 감소 | 전 p95 | 후 p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 카드 선택·해제 / DOM | 116.2ms | 48.8ms | **58.0%** | 159.1ms | 94.2ms |
| 저장된 그래프 탭 / DOM | 124.5ms | 49.4ms | **60.3%** | 163.3ms | 96.7ms |
| 카드 / 두 번째 frame까지 | 130.0ms | 50.3ms | 61.3% | 163.9ms | 95.8ms |
| 그래프 / 두 번째 frame까지 | 146.9ms | 51.1ms | 65.2% | 185.3ms | 98.5ms |

| 실제 저장 경로 | 전 중앙값 | 후 중앙값 | 전 p95 | 후 p95 |
| --- | ---: | ---: | ---: | ---: |
| 카드 / HTTP 시작 → 본문 수신 완료 | 54.5ms | 52.3ms | 61.5ms | 63.0ms |
| 그래프 / HTTP 시작 → 본문 수신 완료 | 55.8ms | 49.2ms | 61.8ms | 56.0ms |
| 카드 / 클릭 → 응답 수신 완료 | **54.8ms** | **103.6ms** | 61.7ms | 149.2ms |
| 그래프 / 클릭 → 응답 수신 완료 | **58.2ms** | **99.8ms** | 64.7ms | 146.6ms |
| 카드 / 클릭 → fetch 시작 | 0.2ms | 49.0ms | 0.3ms | 94.3ms |
| 그래프 / 클릭 → fetch 시작 | 1.2ms | 49.5ms | 3.0ms | 96.8ms |

화면 선택은 실제로 빨라졌지만 **저장 전체가 빨라진 것은 아니다**. HTTP 구간은 대략 49–56ms이며 backend 최적화를 수행하지 않아 그 작은 차이를 backend 개선으로 주장하지 않는다. 오히려 수정 후에는 fetch 시작이 약 49ms 뒤로 밀려 클릭부터 저장 응답까지 더 오래 걸렸다. DOM 반영 시간과 이 대기 시간이 비슷하다. 먼저 표시하는 렌더링이 요청 시작을 늦출 가능성이 있으나, 구체적인 렌더링 비용의 원인은 별도 React/browser 프로파일링으로 확정해야 한다.

각 UI 저장은 전체 workspace를 반환했고 본문 크기 중앙값은 전후 모두 **816,332 bytes(약 797KiB)**였다. 요청 수와 응답 크기는 줄지 않았다. 큰 응답의 파싱·전체 대화 렌더링, 즉시 표시와 서버 확정의 두 번 렌더링, 저장 시작 대기는 후속 최적화 후보다. 이번 시험에서는 DB 쿼리 수·DB 실행 시간·프로파일러의 함수별 비용을 측정하지 않았다.

모든 실행에서 UI PATCH 성공, mutation/page 오류 **0건**, 대화·답변 스냅샷 불변, 종료 후 **모든 turn의 UI 원상 복원**을 확인했다. 측정 원자료는 Git에서 제외한 `agent/python/.runtime/turn-ui-live-perf/`에만 보관했다. 공개 문서에는 시간·건수·본문 크기 집계만 포함하고 실제 질문·Run 값·식별자·화면·trace·payload는 포함하지 않는다.

이는 단일 사용자·로컬 개발 환경의 순차 클릭 시험이다. 페이지 초기 로딩·LLM 답변 생성·운영 환경 INP·처리량·다중 사용자 부하의 개선을 입증하지 않는다. 서버 저장 전 reload/종료하면 마지막 선택을 보존하지 못할 수 있으며 질문 전송은 여전히 저장 확인을 기다린다.

### 실제 측정 재현

backend와 PostgreSQL이 실행 중이고, 역방향 공통 후보 중 **이미 저장된 그래프 탭이 있는 Run**이 필요하다. 해당 상태가 없으면 시험은 오류로 종료하며 대화나 실험을 새로 만들지 않는다. 같은 workspace를 다른 화면에서 조작하지 않는 동안 실행한다. 종료 시 기존 두 UI 필드를 복원하며, 다른 사용자의 최신 선택이 감지되면 덮어쓰지 않고 실패한다. workspace의 revision은 정상 저장 횟수만큼 증가한다.

```sh
git show d26f6e7c421bd52d56871a7ed445f2993862ead2:frontend/src/features/agent/useConversation.ts > /tmp/kplasma-before-turn-ui.ts
cd frontend
mkdir -p ../agent/python/.runtime/turn-ui-live-perf
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_BASELINE_FILE=/tmp/kplasma-before-turn-ui.ts KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-live-perf/before-1.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-live-perf/after-1.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-live-perf/after-2.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_API=http://127.0.0.1:8080 KPLASMA_UI_BASELINE_FILE=/tmp/kplasma-before-turn-ui.ts KPLASMA_UI_PERF_REPORT=../agent/python/.runtime/turn-ui-live-perf/before-2.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
```

로컬 5198 포트가 필요하다. baseline plugin은 테스트 서버에만 적용되며 일반 개발/빌드는 바꾸지 않는다. 각 variant의 두 JSON에서 동작별 `samples`를 합쳐 집계한다. `clickToResponseMs - httpMs`가 fetch 시작 전 대기 시간이다. 측정 JSON에는 시간 표본과 환경 메타데이터만 기록한다. 화면 screenshot과 trace는 만들지 않는다.

### 이전 인공 지연 시험: 느린 저장에 대한 보조 검증

동일한 인공 Run **5개/turn 1개**, 실제 DB·LLM 없이 저장 응답 mock에 **500ms 고정 지연**을 넣었던 시험이다. 워밍업 2회 제외 동작별 20회, 전후 각각 클릭·저장 44회였다. 이는 느린 저장에도 화면 표시가 먼저 되는지 검증하는 별도 시나리오다.

| 동작 / DOM | 전 중앙값 | 후 중앙값 | 전 p95 | 후 p95 |
| --- | ---: | ---: | ---: | ---: |
| 카드 선택·해제 | 520.6ms | 14.2ms | 525.0ms | 15.7ms |
| 저장된 그래프 탭 | 528.5ms | 17.7ms | 529.9ms | 19.0ms |

이 수치는 실제 서버 측정과 합산하지 않는다. 기존 인공 시나리오는 `KPLASMA_UI_PERF_API` 없이 같은 Playwright 명령으로 실행할 수 있다.

## 검증

기능 변경 커밋 `44899b5`의 검증 기록은 아래와 같다. 이번 실측 추가는 시험 도구·Vite 시험 설정·이 문서만 변경하며 제품 동작 코드를 변경하지 않는다.

| 명령 | 기능 변경 시 결과 |
| --- | --- |
| `npm test` | Frontend **183**, TS Agent **33**, 참조 검증 도구 **34** 통과. 외부 원본 전용 **4**건 명시 skip |
| `npm run typecheck` | 통과 (e2e TypeScript 포함) |
| `npm run lint` | 통과 |
| `npm run build` | 통과 |
| `git diff --check` | 통과 |
| `cd frontend && npx playwright test --config src/features/agent/agent-v1.playwright.config.ts agent-v1.pw.ts` | **4/4** 통과, **390/800/1008/1440px** |

실측 추가에서는 실제 HTTP/DB 성능 명령 **4/4**, `npm run typecheck`, `npm run lint`, `npm run verify:public-files`, `git diff --check`를 통과했다. 각 성능 실행의 인공 지연 시험은 모드에 따라 명시 skip했다. 이번에는 제품 단위 테스트·빌드·네 폭 UI 시험을 별도로 반복하지 않았으며 위 기능 변경의 통과 기록과 구분한다.

변경 전 카드·그래프의 즉시 반영 테스트 2건과 거절된 선택 후 잘못된 질문 전송 테스트 1건이 실패하는 것을 확인했다. 구현 후 통과했다. 검토 중 추가한 첫 그래프 탭 실패 복원 테스트도 실패를 먼저 재현한 뒤 수정했다. 첫 타입 검사는 인공 fixture의 JSON 계약 타입 오류로 실패했고 JSON 직렬화 후 최종 검사와 빌드를 통과했다.

자동 테스트는 연속 클릭/오래된 응답, 이전 저장 실패 중 다음 클릭, 카드·결과 탭·Run별 탭의 독립 저장, 저장 거절/응답 유실, 새 대화/초기화, 선택·해제 직후 질문의 저장 확인, 정확한 버전, 첫 탭 실패 복원을 다룬다.

브라우저 검증은 UI 저장 응답을 보류한 채 카드 선택·해제와 이미 저장된 그래프 탭이 먼저 바뀌는지 확인했다. 모든 폭에서 modal 및 페이지 가로 넘침 없음, 키보드 카드 선택, 상세 창 닫기, 기록 모달, 저장 후 reload 복원, pageerror 없음이 통과했다. 390/1440px 인공 카드와 상세 화면을 직접 확인했다. 실제 데이터 screenshot은 만들거나 게시하지 않았다.

`ce-work`의 완료 절차와 `ce-simplify-code`·`ce-code-review`의 재사용/명료성/경쟁 상태/신뢰성/테스트 관점을 요청대로 단독 적용했다. 별도 서브 에이전트 리뷰는 수행하지 않았다. 최종 변경에 남은 구체적 결함은 발견하지 않았으며 팀원 승인은 별도다. Python/backend 단위 테스트·실제 모델 호출·다중 사용자 HTTP/DB 부하 검증은 이번 프론트 변경에서 재실행하지 않았다. 실제 HTTP/DB를 사용하는 위 클릭 시험은 실행했다.

## Post-Deploy Monitoring & Validation

팀 운영 담당자가 반영 후 첫 30분 동안 느린 UI 저장에서도 선택 표시가 먼저 바뀌는지, 저장 실패 안내·reload 복원·질문 대상의 정확한 Run 버전이 맞는지 확인한다. 브라우저 Network에서 `/api/workspace/turns/*/ui` 실패 및 반복 요청을 확인한다. 정상 신호는 최신 클릭 유지, 클릭당 저장 한 건, 저장 후 reload 복원, 확정된 선택으로 질문 실행이다.

늦은 응답으로 선택이 바뀌거나 선택 저장 실패에도 다른 Run으로 질문이 실행되면 해당 프론트 변경을 되돌리고 저장 revision/epoch를 조사한다. API·DB 마이그레이션은 없어 이전 프론트 배포로 되돌릴 수 있다.

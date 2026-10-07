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

## 성능 측정

로컬 Chromium **153.0.8010.12**, Vite 개발 서버, **1440×1000px**, 동일한 인공 Run **5개/turn 1개**, UI 저장에 **500ms 고정 지연**을 적용했다. 수정 전 hook 소스만 Git 기준 커밋에서 가져오고 나머지 앱·fixture·브라우저·지연 설정은 같은 상태에서 비교했다. 실제 DB·LLM·실험 데이터는 사용하지 않았다. 각 동작에서 워밍업 2회를 제외하고 **20회**를 집계했다.

DOM 시간은 실제 브라우저 click 이벤트의 capture 시점부터 선택 class/aria-selected가 바뀐 MutationObserver 시점까지다. frame 시간은 DOM 변경 후 두 번의 requestAnimationFrame까지다. 화면 반영 기회를 지난 근사값이며 실제 픽셀 표시 시점이나 공식 INP가 아니다. p95는 정렬한 20개 표본의 19번째 값이다.

| 동작 / 측정 지점 | 전 중앙값 | 후 중앙값 | 중앙값 감소 | 전 p95 | 후 p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 카드 선택·해제 / DOM | 520.6ms | 14.2ms | 97.3% | 525.0ms | 15.7ms |
| 저장된 그래프 탭 / DOM | 528.5ms | 17.7ms | 96.7% | 529.9ms | 19.0ms |
| 카드 / 두 번째 frame까지 | 530.9ms | 31.1ms | 94.1% | 532.0ms | 31.6ms |
| 그래프 / 두 번째 frame까지 | 556.1ms | 46.5ms | 91.6% | 558.8ms | 48.3ms |

양쪽 모두 워밍업 포함 **44회 클릭 / UI 저장 요청 44회**다. API 요청이나 DB 쿼리를 줄인 최적화가 아니라 저장 대기를 화면 표시 경로에서 제거했다. 카드의 기존 **140ms** 테두리 전환은 유지했다. 이 로컬 결과를 운영 서비스 전체 응답 시간·INP·처리량 개선으로 해석하지 않는다.

페이지 초기 로딩, 실제 DB 쿼리/저장 응답 시간, LLM 응답 시간, 150개 카드·긴 대화에서의 반응, 다중 사용자 부하는 미측정이다. 서버 저장 전 reload/종료하면 마지막 선택을 보존하지 못할 수 있으며 질문 전송은 여전히 저장 확인을 기다린다. 반복 클릭의 저장 큐 길이도 별도 성능 과제다.

### 재현

저장소 루트에서 기준 hook을 별도 파일로 내보낸다. 원본 checkout 파일은 바꾸지 않는다.

```sh
git show d26f6e7c421bd52d56871a7ed445f2993862ead2:frontend/src/features/agent/useConversation.ts > /tmp/kplasma-before-turn-ui.ts
cd frontend
KPLASMA_UI_BASELINE_FILE=/tmp/kplasma-before-turn-ui.ts KPLASMA_UI_PERF_REPORT=/tmp/kplasma-turn-ui-before.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
KPLASMA_UI_PERF_REPORT=/tmp/kplasma-turn-ui-after.json npx playwright test --config src/features/agent/turn-ui-performance.playwright.config.ts
```

로컬 5198 포트가 필요하다. baseline Vite plugin은 명시된 파일의 hook만 테스트 서버에 제공한다. 기본 개발/빌드에는 적용되지 않는다. JSON에는 인공 표본의 시간·브라우저 버전만 기록한다. 장치 부하·브라우저 버전·프레임 주기에 따라 절대 시간은 달라질 수 있다.

## 검증

| 명령 | 최종 결과 |
| --- | --- |
| `npm test` | Frontend **183**, TS Agent **33**, 참조 검증 도구 **34** 통과. 외부 원본 전용 **4**건 명시 skip |
| `npm run typecheck` | 통과 (e2e TypeScript 포함) |
| `npm run lint` | 통과 |
| `npm run build` | 통과 |
| `git diff --check` | 통과 |
| `cd frontend && npx playwright test --config src/features/agent/agent-v1.playwright.config.ts agent-v1.pw.ts` | **4/4** 통과, **390/800/1008/1440px** |
| 위 성능 명령 | before **1/1**, after **1/1** 통과 |

변경 전 카드·그래프의 즉시 반영 테스트 2건과 거절된 선택 후 잘못된 질문 전송 테스트 1건이 실패하는 것을 확인했다. 구현 후 통과했다. 검토 중 추가한 첫 그래프 탭 실패 복원 테스트도 실패를 먼저 재현한 뒤 수정했다. 첫 타입 검사는 인공 fixture의 JSON 계약 타입 오류로 실패했고 JSON 직렬화 후 최종 검사와 빌드를 통과했다.

자동 테스트는 연속 클릭/오래된 응답, 이전 저장 실패 중 다음 클릭, 카드·결과 탭·Run별 탭의 독립 저장, 저장 거절/응답 유실, 새 대화/초기화, 선택·해제 직후 질문의 저장 확인, 정확한 버전, 첫 탭 실패 복원을 다룬다.

브라우저 검증은 UI 저장 응답을 보류한 채 카드 선택·해제와 이미 저장된 그래프 탭이 먼저 바뀌는지 확인했다. 모든 폭에서 modal 및 페이지 가로 넘침 없음, 키보드 카드 선택, 상세 창 닫기, 기록 모달, 저장 후 reload 복원, pageerror 없음이 통과했다. 390/1440px 인공 카드와 상세 화면을 직접 확인했다. 실제 데이터 screenshot은 만들거나 게시하지 않았다.

`ce-work`의 완료 절차와 `ce-simplify-code`·`ce-code-review`의 재사용/명료성/경쟁 상태/신뢰성/테스트 관점을 요청대로 단독 적용했다. 별도 서브 에이전트 리뷰는 수행하지 않았다. 최종 변경에 남은 구체적 결함은 발견하지 않았으며 팀원 승인은 별도다. Python/backend 테스트·실제 모델 호출·실제 HTTP/DB 부하 검증은 이번 프론트 변경에서 재실행하지 않았다.

## Post-Deploy Monitoring & Validation

팀 운영 담당자가 반영 후 첫 30분 동안 느린 UI 저장에서도 선택 표시가 먼저 바뀌는지, 저장 실패 안내·reload 복원·질문 대상의 정확한 Run 버전이 맞는지 확인한다. 브라우저 Network에서 `/api/workspace/turns/*/ui` 실패 및 반복 요청을 확인한다. 정상 신호는 최신 클릭 유지, 클릭당 저장 한 건, 저장 후 reload 복원, 확정된 선택으로 질문 실행이다.

늦은 응답으로 선택이 바뀌거나 선택 저장 실패에도 다른 Run으로 질문이 실행되면 해당 프론트 변경을 되돌리고 저장 revision/epoch를 조사한다. API·DB 마이그레이션은 없어 이전 프론트 배포로 되돌릴 수 있다.

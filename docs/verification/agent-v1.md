# Agent graph v1 구현·검증 기록

작성일: 2026-10-05. 구현 브랜치: `feat/agent-graph-v1`.

**후속 회귀 수정:** 아래 완료 검증·평가는 최초 구현 기록이다. 사용자가 보고한 기본 범위 검색과 원본 UI 차이는 이 검증에서 놓쳤다. 현재 `interpret-2` / `v1-2026-10-05.3`의 규칙과 최신 결과는 [순·역방향 패리티 수정 기록](agent-v1-search-parity.md)을 따른다. 최초 140개 질문 평가 점수를 수정된 프롬프트의 점수로 취급하지 않는다.

## 실행 범위

신규 질문은 Python LangGraph v1으로만 실행한다. 등록된 operation은 `forward_lookup`, `reverse_search`, `compare_runs`, `explain_change`, `explain_concept`다. 기존 JavaScript fallback 소스·테스트와 과거 스냅샷 렌더러는 유지하지만 자동 대체 실행은 없다. 모델 설정은 사용자 지정 `gpt-5.6-luna`, `reasoning.effort=none`이다. API 키는 서버의 로컬 환경에서만 읽는다.

LLM은 질문을 strict JSON으로 해석하고, 코드가 누락 조건·Run 선택·단위·숫자의 원문 대응을 검증한다. 수치 조회·정렬·비교·변화율은 Python 코드만 계산한다. 결과는 고정된 Run 버전으로 재계산 검증한 뒤 표시한다. 설명은 검증된 비교의 정성적 방향 또는 개념 주제만 받아 생성한다. 일반 지식 사용과 인과관계 미확정을 코드에서 표시하며, 미검증 숫자·출처·명백한 방향 모순은 출력 검증과 한 차례 repair를 거친다. RAG·검토 문헌 검색은 후속 범위다.

## 계획에서 구체화한 구현 선택

- 체크포인트는 PostgreSQL에 저장하지만 Python에 DB 자격증명을 주지 않는다. `DurableSaver`가 LangGraph의 채널/쓰기 직렬화를 수행하고, Spring 내부 API가 요청 행 잠금·generation·revision·lease를 확인한 동일 트랜잭션에서 JSON/base64 payload를 저장한다. `durability="sync"`이고 저장 실패 시 성공으로 진행하지 않는다. 메모리는 캐시일 뿐 복구의 권위자가 아니다.
- 완료·실패·취소·초기화의 체크포인트/manifest 정리는 같은 서버 트랜잭션에서 수행한다. 별도의 비동기 정리 큐보다 원자적 정리를 택했다. 최종 turn과 COMPLETED 전이도 같은 트랜잭션이며 응답 유실 재시도에 동일 결과를 반환한다.
- Python 모듈은 `graphs/v1.py`, `domain/`, `explanations/engine.py`, `persistence/checkpointer.py`로 배치했다. 계획의 세부 파일 분할은 실제 책임 단위에 맞게 합쳤으며 해석·계산·검증·설명·표시의 노드 경계는 유지한다.
- 초기 프로토타입의 고정 `150` 안내는 신규 Agent/공통 상단에서 “등록된 Run”으로 바꿨다. 비어 있거나 일부만 등록된 환경에서 존재하지 않는 Run 개수를 표시하지 않기 위한 문구 변경이다.
- 기존 fallback UI 전용 Playwright 구성은 역사적 검증용으로 보존했다. 현재 기본 종단 검증은 v1용 구성이고, 오프라인 CI의 모델 응답만 테스트 모듈로 대체한다. 제품 worker에 테스트 모델 또는 fallback 전환 설정은 없다.

## 완료된 검증

아래는 로컬 실행 결과다. 팀원 clean clone·도메인 전문가 검토 완료를 의미하지 않는다. 원격 CI 결과는 PR에서 별도 확인한다.

| 검증 | 명령/경로 | 관찰 결과 |
|---|---|---|
| 실제 모델 연결 | `ModelClient`의 Responses API | `gpt-5.6-luna`/`none`, strict structured output 동작 확인 |
| Python 수치·계약·설명·그래프·복구 | `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q` | 164개 통과 (tests + eval harness 전체) |
| Backend 영속성·기존 기능 | `backend/gradlew -p backend test --console=plain` (Java 21) | 15 suite, 129개 통과 |
| 실제 프로세스 장애 | `scripts/agent/fault-verification.py` | 15/15 SIGKILL/회수 시나리오 통과, 독립 PostgreSQL·실제 HTTP·실제 saver 사용 |
| Spring 서버 재시작 | `npm run test:agent:restart` | 3/3 통과: 접수 요청, 추가 입력/checkpoint, 완료 답변·멱등 재개를 서버 SIGKILL 후 복원 |
| 오프라인 v1 종단 | `npm run test:e2e` | 390/800/1008/1440px 통과; HTTP/DB/그래프 실제 구현, 모델만 고정 응답 |
| 실제 모델 v1 종단 | `npm run test:e2e:live` | 같은 네 폭에서 다섯 도구·누락 조건 재개·reload·정확한 버전·중복 turn 방지 통과 |
| 개별 조건 후보 UI | `frontend/src/features/agent/agent-v1.playwright.config.ts` | 인공 snapshot으로 네 폭에서 개별 조건 탭·제한 안내·기록 모달·reload·넘침 4/4 통과 |
| 정적 검사·빌드 | `npm run typecheck`, `npm run lint`, `npm run build`, Python Ruff/Mypy, `git diff --check` | 통과; frozen/offline uv sync 재현 확인 |
| 기존 JS/UI 회귀 | `npm test` | UI 126개, TS Agent 33개, 검증 도구 34개 통과; 기존 외부 원본 전용 4개 skip |
| 외부 원본 scalar 대조 | `KPLASMA_PROTOTYPE_ROOT=... npm run verify:agent-reference` | 실제 150 Run, 순방향 151건 일치; 역방향 25건 중 22건 일치, 3건은 계획 X5의 비가용 값 제외 차이만 존재 |

최종 UI 수정 후 오프라인 종단 검증은 네 폭 모두, 실제 모델 종단 검증은 `KPLASMA_V1_LIVE_WIDTHS=390`으로 재실행해 통과했다. 최종 `npm test`·typecheck·lint·build도 재실행해 통과했다.

SIGKILL 시나리오는 수치 체크포인트 직전/직후, 모델 응답 후 draft 저장 전, draft 저장 후, 설명 검증 후, 변화 설명 draft, finalize 전/응답 유실, interrupt 저장/대기 표시 사이, 추가 입력 저장 전후 적용, 만료 generation, 설정 버전 불일치를 포함한다. 중단 중 새 Run 버전을 등록한 경우에도 기존 manifest의 정확한 버전·수치·역방향 후보 순서가 유지됨을 확인했다. 만료된 worker의 checkpoint뿐 아니라 finalize도 거부했다. 저장된 draft 이후에는 모델 재호출 없이 복구했고 완료 turn은 한 건이었다. 모델 응답 후 저장 전의 호출은 재실행될 수 있다.

이 검증에서 `get_state().next`가 비어 있어도 pending write를 다음 단계로 반영해야 하는 복구 오류를 발견했다. 이제 durable `answer`가 존재할 때만 완료 상태로 취급하며, 실제 장애 시점 payload를 복원하는 회귀 테스트를 추가했다. 추가 입력에는 직전 대기 질문을 함께 전달하여 “0 W”처럼 짧은 답변의 슬롯이 유실되지 않도록 수정했다.

## 평가와 남은 검증 범위

[평가 실행기](../../agent/python/evals/README.md)로 **최종 프롬프트의 140개 인공 질문을 각각 세 번 새로 호출**했다. 419/420(99.76%), 필수 항목 3053/3054(99.97%), 잘못된 실행 허용 0건, 모델 API 오류 0건이었다. 실패 한 건은 필요한 추가 질문은 올바르게 반환했지만 추출한 operation을 생략한 사례다. 실패도 분모에 포함했다. 실행기는 모든 사례 일치를 요구하므로 exit 1을 반환했으며, 이를 전 사례 통과로 표시하지 않는다. 계획의 필수 slot 95%·critical 잘못된 dispatch 0건 기준은 충족했다. 모델/추론은 `gpt-5.6-luna`/`none`이며 프롬프트 해시를 결과와 함께 기록했다.

그 전에 보존된 이전 420개 출력을 최종 guard로 재채점한 413/420 결과와 영향 사례의 추가 호출 15/15 결과도 보존했다. 이 재채점 결과와 위의 최종 프롬프트 신규 호출 결과를 혼동하지 않는다.

설명도 **최종 프롬프트로 변화 20개·개념 20개를 각각 세 번 새로 점검**했다. 120/120 경로가 자동 검증/예상 응답 검사를 통과했다. 이 중 111개는 실제 모델 응답이고, 9개는 관찰 변화/비교 가능 지표가 없어 코드가 모델 호출 없이 제한 결과를 반환하는 사례다. repair와 API 오류는 없었다. 초기 120개 경로에서 발견한 허위 관찰 참조를 고친 이전 기록도 유지했다. 이 점수는 과학적 정확도나 도메인 전문가 평가 점수가 아니다.

질문 원문·모델 응답·trace·연결 토큰은 Git에서 제외한 로컬 `.runtime/`에만 저장한다. 외부 실제 Run의 scalar 대조는 별도 프로세스 메모리에서만 수행하고 모델에 해당 Run payload를 전송하지 않았다.

일반 지식 설명의 과학적 정확성을 schema·규칙 검증만으로 보장하지 않는다. 실제 장비별 인과 해석과 검토 문헌/RAG는 후속 검토 범위다. 실제 150 Run의 scalar 값·검색 순서는 위의 별도 원본 대조로 확인했다. 전체 원본 화면·곡선 비교와 팀 clean clone 검증은 이번 범위에서 수행하지 않았다. 기존 fallback 외부 원본 테스트는 원본 패키지가 제공된 환경에서만 실행하며 기본 CI에서는 명시적으로 skip한다.

## 운영 확인

로컬 worker 로그는 요청 내용·원본 데이터·키를 출력하지 않고 버전/모델 설정과 안전한 오류 코드만 남긴다. `MODEL_UNAVAILABLE`, `MODEL_ATTEMPT_LIMIT`, `CLAIM_ATTEMPT_LIMIT`, `RECOVERY_STATE_INVALID`, `RECOVERY_VERSION_MISMATCH`, `STALE_CLAIM`을 확인한다. 정상 신호는 QUEUED → RUNNING → COMPLETED 또는 NEEDS_INPUT → 재개이며, worker 재시작 후 만료 lease 요청이 복구되고 중복 turn이 없어야 한다.

배포 직후 팀 운영자가 다섯 인공 예제와 한 번의 추가 입력/재시작을 확인한다. 같은 요청이 반복 회수되거나 실패가 누적되면 worker를 멈추고 오류 코드와 버전을 확인한다. fallback으로 자동 전환하지 않는다. 완료 답변은 재생성하지 않으며 미완료 작업의 모델/프롬프트/수치 정책이 바뀌면 명시적으로 실패시킨다. Phoenix는 이번 필수 경로에 추가하지 않았다.

## 리뷰 중 보완한 경계

명시한 숫자 조건의 누락과 미근거 수치 변경을 모두 검증하고, 구조화된 작업 선택/추가 입력 이후에도 같은 검증을 다시 적용한다. 모호한 기준/대상 역할은 확인 질문으로 넘긴다. 이전 비교의 지표 범위는 유지하며 변경 요청이 있을 때만 바꾼다. 개념 정의는 한 주제, 차이/관계는 서로 다른 두 주제로 제한한다. 잘못된 추가 입력은 이력을 보존한 채 재입력을 받고, 유효한 0 값은 누락으로 보지 않는다.

단계별 모델 호출은 요청 revision마다 네 번, worker claim은 최초 실행을 포함하여 세 번으로 제한한다. 소진 시 명시 실패와 안전한 오류 코드를 저장한다. 기본 서버는 loopback에만 바인딩한다. Run 삭제·기준 변경이 종류 판별 전에 발생하면 서버가 변경 사실을 보존하고, 판별 후 문맥 의존 작업만 취소한다. 개념 설명은 계속 진행하며 새 대화·초기화는 즉시 취소한다. 프롬프트 실제 해시도 복구 fingerprint에 포함해 수정 전 checkpoint를 다른 지침으로 조용히 실행하지 않는다.

UI 후보의 상세 조회·후속 질문·판단 저장에는 결과에 저장된 정확한 Run 버전만 사용한다. 전송 응답 유실 후 서버 요청을 복원하고, 기준 변경 중인 요청과 늦게 도착한 이전 polling 응답을 분리한다. 추가 질문 전환 시 입력 초안을 비우며, 개별 조건 후보와 검증된 조건/평가값도 판단 기록에 보존한다. 관련 회귀 사례를 추가해 확인했다.

에이전트 코드 리뷰는 정확성·복구·보안·API·마이그레이션·UI 경쟁 상태 등 13개 관점으로 진행했다. 확인된 결함 18개를 수정하고 현재 코드와 회귀 검증을 재확인했으며, 제출 시 남은 실행 가능한 지적은 없었다. 이는 작성자 외 팀원 승인이나 독립 도메인 전문가 검토를 대신하지 않는다. 전체 150 Run의 checkpoint 크기·지연시간 성능 측정은 수행하지 않았다.

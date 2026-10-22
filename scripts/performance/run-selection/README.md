# 실험 선택 화면 A/B/C 측정

실제 Spring HTTP 요청과 PostgreSQL을 사용하며 LLM은 호출하지 않는다. 150 / 1만 / 10만 / 100만 건 모두 결정론적으로 만든 **인공 데이터**다. 실제 데이터·API 키·서비스 DB에 접근하지 않는다.

- A: 기존 전체 후보 JSON 고정·전송·브라우저 검색
- B: 원본 DB 최신 목록을 직접 검색·keyset 30개 페이지 조회 + 선택한 버전 K개만 저장
- C: B에 원본 `run` 정렬용 B-tree, 원본 `run_version` 부분 문자열 검색용 GIN `pg_trgm` 추가. 기존 선택 항목 부분 B-tree는 B/C 공통이다.

## 도구와 구간

| 도구 | 측정 대상 |
| --- | --- |
| `run.py` / Python `perf_counter` | 실제 submit → claim → heartbeat → needs-input 흐름에서 후보 준비 HTTP, 준비된 페이지 HTTP를 각각 측정 |
| k6 / `api.py` | 준비된 세션의 목록·검색·다음 페이지·별도 건수 집계 HTTP, 1 VU × 100회 × 3블록(100만 건은 10회 × 3블록의 규모 확인 표본). LLM·seed·렌더링 제외 |
| Playwright + Vite / `browser.mjs` | 실제 React 선택 패널을 준비된 API에 연결. 탐색 시작부터 체크박스 표시·paint까지, 입력부터 검색 결과 표시까지 |
| PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` | SQL 실행 계획·읽은 버퍼·정렬·인덱스 사용 |
| `pg_stat_statements` | API 측정 구간의 SQL calls·실행 시간·행 수·WAL |
| JFR | 서버의 객체 할당·GC·실행 샘플. JDBC 연결 획득 시간과 HTTP 시간을 혼동하지 않는다. |

첫 화면 측정은 **이미 후보가 준비된 상태**에서 시작한다. 선택 세션 준비 비용과 별도로 보고하며, 준비 HTTP + 첫 페이지 HTTP 합계도 보고한다. 이를 전체 Agent 응답 개선율이라고 부르지 않는다. 첫 30개는 전체 건수 집계 완료를 기다리지 않는다. 일반 목록은 각 분기에서 최대 31개를 먼저 읽고, 3글자 이상 검색은 GIN의 일치 식별자와 기존 Run PK를 먼저 연결한 뒤 정렬한다. 두 글자 검색은 정렬 경로를 유지하며 trigram만으로 탐색량이 줄었다고 가정하지 않는다. 페이지 준비/HTTP/브라우저 시간은 겹치는 구간이므로 단순 합산하지 않는다. 검색 결과 표시 시간에는 제품의 300ms 입력 대기가 포함된다.

## 격리와 자원

`compose.yaml`의 전용 DB만 사용한다. `seed.py`는 DB 컨테이너의 전용 라벨을 검사한 뒤 해당 DB만 초기화한다. 실제 `.env`를 읽지 않으며 임의 DB URL을 받지 않는다. 원시 JSON/JFR/스크린샷/JAR는 Git에서 제외된 `.local/performance/run-selection/`에 저장한다.

Java 21, PostgreSQL 18.6, DB CPU 2개/메모리 6GB/shared_buffers 256MB/work_mem 16MB, Hikari 기본 10개를 공통 사용한다. 초기 2GB 힙에서 A 100만 건이 OOM으로 실패하여 사용자의 승인으로 **본 비교는 A/B/C 모두 `-Xms512m -Xmx8g`**로 실행한다. Java 8GB·DB 3GB에서 JSON 저장 중 DB OOM도 확인하여 전용 DB는 6GB로 늘렸다. 2GB 예비 측정은 별도 보존하며 서로 다른 힙 측정치를 같은 전후 비교로 섞지 않는다. 8GB는 벤치마크 설정이며 제품 기본 설정 변경이 아니다.

## 실행

```sh
docker compose -f scripts/performance/run-selection/compose.yaml up -d
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home backend/gradlew -p backend bootJar
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
SELECTION_BENCH_HOOK="$PWD/scripts/performance/run-selection/hook.sh" \
python3 scripts/performance/run-selection/run.py --variant C \
  --jar backend/build/libs/analysis-agent-0.0.1-SNAPSHOT.jar \
  --output .local/performance/run-selection/live/C/heap8-db6 --heap 8g
```

JAR 이름은 실제 `backend/build/libs/` 결과를 확인한다. A는 변경 전 JAR와 선택 컴포넌트/API 사본을 보존한 후 실행한다. 검증한 최종 bootJar에서 `python3 scripts/performance/run-selection/variants.py <jar> .local/performance/run-selection/live`으로 B/C를 만든다. B는 V11 인덱스 마이그레이션 파일만 제외하며 나머지 ZIP 항목 바이트가 모두 같은지 검증한다. B JAR는 V10까지 포함하고 C만 V11을 적용한다. 새 Flyway 마이그레이션을 적용한 DB에서 오래된 JAR를 실행하지 않는다. A → B → C 순서로 전용 DB를 사용하거나 별도의 전용 DB를 준비한다.

각 규모에서 서버 재시작 → 동일 seed → 워밍업 2회 → 독립 후보 준비/조회 10회를 진행한다. 뒤이어 준비된 마지막 세션에서 브라우저와 API를 순차 실행한다. 동시에 다른 부하 시험·빌드·테스트를 실행하지 않는다. 기본 브라우저 반복은 20회, 10만/100만은 10회이며 첫 표시 제한 시간은 20초다. 실패는 숨기거나 성공 표본으로 바꾸지 않는다.

`--heap`, `--sessions`, `--sizes`로 진단 조건을 명시할 수 있다. `environment.json`에 기록되며, 기존 `sessions.jsonl`은 덮어쓰지 않는다. 선택 세션 준비·페이지·검색에서 전체 후보를 복사하지 않는다. 원본 검색 문자열과 정렬 키는 원본 등록/갱신 시 생성되며, 측정 전 seed·마이그레이션·인덱스 작성 시간은 요청 지연에서 제외한다. 선택 전 요청별 옵션 행은 0, 두 개 선택 후에는 2여야 한다. 명시적인 전체 선택은 사용자가 누른 시점의 일치 버전을 저장하므로 이 작업만 선택 수 N에 비례한다. 전체 건수 COUNT 비용은 별도로 측정한다.

100만 건 API는 전체 스캔이 남은 B의 반복 비용을 제한하기 위해 B/C 모두 시나리오별 30회(10회 × 3블록)를 실행한다. 150~10만 건은 계획의 300회를 유지하며, 100만 건의 작은 표본 p95를 안정적인 서비스 지표로 주장하지 않는다. 독립 후보 준비 세션은 규모별 10회를 유지한다.

## A 기준선과 집계

사본 없는 재측정은 기존 A 기준선 원시 결과를 재사용하고 새 B/C를 `live/`에 저장한다. 같은 자원·인공 데이터 규칙이지만 측정 시점은 다르다. 이전 사본 B/C와 A 원시 기록은 덮어쓰지 않는다. 이전 구현 결과는 [기존 보고서](../../../docs/verification/2026-10-22-실험-선택-페이지-조회-성능-비교.md)에 보존한다.

A의 기준 커밋은 `5c5e82f9515e390202392673a92c89b7671518de`다. 변경 전 체크아웃에서 `bootJar`를 빌드해 `A/backend.jar`로 보관하고, `frontend/src/features/agent/RunSelectionPanel.tsx`와 `frontend/src/api/agent.ts`를 각각 `A/RunSelectionPanel.tsx`, `A/agent-api.ts`로 보관한다. 보관한 컴포넌트의 API import는 `./agent-api`, 표시 유틸 import는 `/frontend/src/features/agent/agent-contract`로 바꾼다. 보관한 API의 `request` import는 `/frontend/src/api/client`로 바꾸고 계약 import는 원래 `agent` 패키지를 사용한다. 제품 코드는 바꾸지 않는 측정용 import 조정이다. 현재 제품 코드로 A를 대신 측정하지 않는다.

```sh
python3 scripts/performance/run-selection/report.py \
  .local/performance/run-selection/live \
  --output .local/performance/run-selection/live/summary.json
```

집계기는 `A|B|C/heap8-db6/<규모>`를 읽고 자원 설정이 다른 결과는 거부한다. `sessions.jsonl`의 실패와 `browser.json`의 시간 초과를 별도로 보존한다. `browser-process-error.txt`가 있으면 hook 실패 여부도 확인해야 한다. k6는 각 시나리오의 실제 표본 수와 실패율을 함께 확인한다.

기능·반응형 검증은 성능 측정과 별도로 준비된 150개 세션에서 `node scripts/performance/run-selection/qa.mjs <세션 경로>`로 수행한다. 선택·검색·새로고침·세 일괄 선택·K=2 재개와 390/800/1008/1440px 가로 넘침을 검사한다. 측정 중에는 실행하지 않는다.

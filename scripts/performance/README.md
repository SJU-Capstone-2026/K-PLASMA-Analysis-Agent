# 파일 업로드 벤치마크

실제 HTTP 접수·단일 작업자·파서·PostgreSQL 등록을 측정한다. LLM을 호출하지 않는다. 기본 인공 입력은 기능 smoke용 소형이며, [2026-10-15 결과](../../docs/verification/2026-10-15-파일-업로드-성능-개선.md)의 1.545GB 입력과 구분한다.

## 격리 환경 준비

서비스 DB·원본 보관소를 사용하지 않는다. 아래 이름·포트가 비어 있는지 먼저 확인한다. 중복·갱신 검증을 위해 harness는 **자기 DB와 storage를 매회 초기화**한다.

```sh
mkdir -p .local/performance/upload/current
python3 scripts/performance/generate_upload_fixture.py --out .local/performance/upload/synthetic
backend/gradlew -p backend bootJar --console=plain
docker run -d --name kplasma-upload-benchmark-local --cpus=2 --memory=3g \
  -p 127.0.0.1:15451:5432 \
  -e POSTGRES_DB=upload_benchmark -e POSTGRES_USER=upload_benchmark \
  -e POSTGRES_PASSWORD=isolated-upload-benchmark \
  postgres:18.6-alpine3.24 \
  -c shared_preload_libraries=pg_stat_statements -c track_io_timing=on \
  -c pg_stat_statements.track_planning=on
```

PostgreSQL 준비 후 확장을 만든다. 비밀번호는 위 격리 환경의 예시 값이며 서비스 자격 증명과 무관하다.

```sh
docker exec kplasma-upload-benchmark-local psql -U upload_benchmark -d upload_benchmark \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements'
```

빌드한 실행 JAR 경로를 명시해 별도 터미널에서 실행한다. 저장소 안의 `backend/storage`나 서비스 포트를 지정하지 않는다.

```sh
java -Xms256m -Xmx2g \
  -Dkplasma.import-timing.enabled=true \
  -Dkplasma.import-timing.file="$PWD/.local/performance/upload/current/timing.jsonl" \
  -jar backend/build/libs/analysis-agent-0.0.1-SNAPSHOT.jar \
  --server.address=127.0.0.1 --server.port=18551 \
  --spring.datasource.url=jdbc:postgresql://127.0.0.1:15451/upload_benchmark \
  --spring.datasource.username=upload_benchmark \
  --spring.datasource.password=isolated-upload-benchmark \
  --spring.datasource.hikari.maximum-pool-size=2 \
  --kplasma.storage-root="$PWD/.local/performance/upload/current/storage"
```

JAR 이름은 해당 빌드의 `backend/build/libs/` 출력과 대조한다. 별도 worktree에서도 절대 경로를 쓰며 여러 서버가 같은 DB·storage를 사용하지 않게 한다.

## 신규·중복·갱신·ZIP

```sh
python3 scripts/performance/upload_benchmark.py \
  --variant current --base http://127.0.0.1:18551 \
  --container kplasma-upload-benchmark-local \
  --manifest .local/performance/upload/synthetic/manifest.json \
  --timing .local/performance/upload/current/timing.jsonl \
  --storage .local/performance/upload/current/storage \
  --output .local/performance/upload/current-results \
  --iterations 10 --warmups 1 \
  --golden .local/performance/upload/golden-new.json \
  --save-seed .local/performance/upload/seed
```

첫 비교군의 `golden-new.json`을 다른 비교군에서도 공유한다. 시각·버전 ID를 제외한 전체 수치·샘플과 원본 SHA, 독립 스칼라 정답을 매회 확인한다. 매회 UUID·시각은 달라지는 것이 정상이다.

- ZIP: 같은 인자에 `--scenario zip --iterations 5`. ZIP 생성은 시간에서 제외한다.
- 동일 원본: `--scenario duplicate --seed .local/performance/upload/seed --iterations 5`. 150개 모두 DUPLICATE, 버전 추가 없음.
- 갱신: 생성기에 `--updated --out .local/performance/upload/synthetic-updated`를 전달한 뒤 해당 manifest와 별도 `golden-updated.json`, `--scenario update --seed ... --iterations 5`를 사용한다. 150 Run·300 버전을 검증한다.
- 계측 off: 같은 A JAR를 `-Dkplasma.import-timing.enabled=false`로 재시작하고 **새 variant `A0`/output**과 `--no-timing`으로 실행한다. 벽시계 비교와 값 검증만 가능하다.
- 집계: `python3 scripts/performance/analyze_upload_benchmark.py .local/performance/upload --variants current`.
- harness 검증: `python3 -m unittest discover -s scripts/performance -p test_upload_benchmark.py`.

비교군마다 별도 보존한 JAR·계측 로그·실행 설정을 사용한다. `--start-index`로 본 측정 번호를 이어갈 수 있으며, 워밍업 파일은 본 측정과 별도 이름이다. `A0`는 계측 off 집계용 이름이다. 벽시계 임계치를 CI 통과 기준으로 사용하지 않는다.

## 실제 볼륨·보관 원칙

소형 smoke를 대용량 성능 결과로 발표하지 않는다. 외부로 공급받은 비공개 파일 크기·행/격자 프로필은 `--profile /비공개/profile.json`으로 사용한다. `--inventory`는 원본 파일을 읽고 크기·shape를 추출할 뿐 원본을 수정하지 않는다. 실제 물리 수치가 담긴 파일·golden·trace·DB·프로필은 Git이나 CI artifact로 올리지 않는다.

폴더의 파일별 byte, ZIP의 압축/해제 byte, 파싱 행/격자 수, 성공/실패 수를 결과와 함께 기록한다. DB 호출 시간·엔진 실행 시간·연결 점유 시간은 중첩되므로 더하지 않는다. 상세 측정 경계와 제한은 검증 보고서를 따른다.

완료 후 자기 서버와 전용 컨테이너만 종료한다. 서비스 컨테이너나 원본을 정리 대상으로 사용하지 않는다.


## 업로드 중 조회 B/C 비교

[병행 조회 계획](../../docs/plans/2026-10-15-업로드-중-조회-대기와-응답-성능-비교-계획.md)에 따라 동일한 파일을 등록하면서 `GET /api/run-versions/{id}`를 초당 5회 호출한다. LLM·Agent·브라우저 렌더링을 포함하는 시험이 아니다. 실행 도구는 Python 3, Java 21, Docker/PostgreSQL, k6이며 원시 자료는 `.local/performance/upload-query/`에 보관한다.

### 고정 조회 seed

파서는 정해진 150개 조건만 허용한다. 따라서 **조회용 세 Run을 먼저 변경된 인공 원본으로 등록한 뒤, 원래 150개를 등록**한다. 매회 결과는 147개 신규·3개 갱신, 150개 현재 Run·153개 버전이다. 조회는 seed의 과거 버전 ID에 고정한다. 서로 다른 조건 153개를 만들거나 원래 파일을 중복 등록하는 방식은 사용하지 않는다.

1. 같은 볼륨 프로필에서 조회 응답 크기가 작은/중간/큰 세 조건을 선택하고 `generate_upload_fixture.generate(selected_profile, seed_source, updated=True)`로 인공 seed를 만든다.
2. 전용 DB에서 `upload_benchmark.post()`로 등록하고 SUCCESS·READY를 확인한다. `upload_benchmark.verify(..., 'new')`로 검증한다.
3. 세 `GET /api/run-versions/{id}`의 원본 응답 바이트를 SHA-256으로 계산한다. `queries.json`에 `runId`, `runVersionId`, `sha256`, `bytes`를 저장한다. 제품 API는 수정하지 않는다.
4. `upload_benchmark.save_seed(container, storage, seed_dir)`로 DB·파일 스냅샷을 만든다. 본 측정은 매회 이를 복원한다. `.local` 안의 자기 벤치마크 DB·storage에만 실행한다.

### 한 배치 실행 예시

B와 C에는 같은 계측 소스 패치를 적용한 JAR를 사용하고 각 JAR·패치의 SHA-256을 기록한다. 현재 풀 크기와 `minimum-idle`을 동일하게 지정하고, JVM을 다시 시작할 때 전체 볼륨 워밍업 한 회를 제외한다. 현재 제품 코드의 풀 크기를 수정하지 않는다. 연결 1개 진단에서는 먼저 풀 2개 이상으로 스키마를 마이그레이션한 전용 DB를 사용하고, B/C 모두 `--spring.flyway.enabled=false`로 시작한다. 이 버전의 Flyway는 시작 시 추가 연결을 요청하므로 풀 1개로 마이그레이션까지 실행하면 서버 시작이 실패한다. 스키마 준비·시작 시간은 성능 측정 밖이며 제품 설정에는 이 옵션을 적용하지 않는다.

```sh
python3 scripts/performance/upload_query_benchmark.py \
  --base http://127.0.0.1:18552 --variant C --pool 2 \
  --container kplasma-upload-benchmark-query-20261015 \
  --manifest .local/performance/upload/synthetic/manifest.json \
  --queries .local/performance/upload-query/queries.json \
  --seed .local/performance/upload-query/seed \
  --storage .local/performance/upload-query/active/storage \
  --timing /absolute/path/to/current-server/timing.jsonl \
  --pid SERVER_PID \
  --output .local/performance/upload-query/results \
  --golden .local/performance/upload/golden-new.json \
  --scenario combined --index 1
```

`SERVER_PID`와 timing 경로는 방금 시작한 전용 서버의 실제 값으로 바꾼다. `--scenario query`는 조회만 60초, `upload`는 업로드만, `combined`는 조회 90초 중 10초 후 업로드를 시작한다. `--warmup`은 집계에서 제외한다. 계측을 끈 JAR 실행에는 `--no-timing`을 전달한다. 같은 출력 경로를 덮어쓰지 않으며 실패 결과도 보존한다.

k6가 정해진 부하를 발행하지 못한 횟수, HTTP 오류와 응답 해시 불일치를 함께 검사한다. `db.acquire`는 풀 연결 획득 호출 전체 시간으로 순수 대기만을 뜻하지 않는다. `http_req_blocked`를 DB 대기로 해석하지 않는다. 서버 업로드 진입부터 마지막 게시 commit까지 시작한 조회를 요청 ID로 연결하고, 창 이후 완료된 요청도 포함한다.

```sh
python3 scripts/performance/analyze_upload_query_benchmark.py .local/performance/upload-query
python3 -m unittest discover -s scripts/performance -p 'test_*upload*py'
```

통계 단위는 요청 한 건이 아닌 배치이며 B/C 각각 같은 번호끼리 비교한다. 기본 풀 10, 선행 설정 2, 진단용 1의 결과를 합치지 않는다. 계측 off/on 제어 실험에서는 클라이언트 지표만 비교하고 DB 시간을 추정해 채우지 않는다. 전체 볼륨 기준선·본 측정 횟수와 순서는 계획 및 실행 보고서를 따른다.

최종 [업로드 중 조회 B/C 실측 결과](../../docs/verification/2026-10-15-업로드-중-조회-대기와-응답-성능-비교.md)에 기본 풀과 연결 부족 진단을 구분했다. 분석 출력 `summary.json`의 `groups`에는 유효 측정 배치가, `excluded_trials`에는 실행 실패·불완전 부하·상관관계 누락 등의 사유가 남는다. 상관관계가 있는 HTTP 오류는 유효한 부하 결과로 집계하며 성공 요청으로 바꾸지 않는다.

## 연결 10개 고정 · 짧은 단계별 조회 부하

[후속 계획](../../docs/plans/2026-10-15-연결-10개-고정-업로드-중-조회-단계별-부하-비교-계획.md)의 실행기는 `upload_query_ramp.py`다. 보존한 B/C 계측 JAR, 위에서 만든 조회 seed/`queries.json`, 원래 인공 fixture/전체 응답 golden을 재사용한다. 입력과 JAR 해시는 선행 실험에 고정되어 있으며 다른 제품 빌드를 그대로 대체하면 안 된다.

```sh
python3 scripts/performance/upload_query_ramp.py \
  --artifacts .local/performance/upload-query \
  --fixture-root .local/performance/upload \
  --output .local/performance/upload-query-ramp-NEW \
  --container kplasma-upload-benchmark-query-20261015 \
  --java "$JAVA_HOME/bin/java"
```

전용 PostgreSQL 컨테이너(포트 15452)가 먼저 준비돼 있어야 한다. Java는 실행기가 포트 18552에서 시작·종료하며, 결과 경로는 기존 실험과 겹치면 실행을 거부한다. 전용 DB·storage는 매 배치와 종료 시 seed로 복원한다. 서버가 중단된 뒤에만 미완료 작업을 정리한다.

- 연결 10개·VU 60개 고정. B에서 20→50→100→200→400건/초를 탐색하고, 지연 시작 단계와 직전 단계만 B/C 각 3회 확인한다. 끝까지 지연이 없으면 400건/초만 비교한다.
- `selection.json`은 C를 측정하기 전에 비교 단계를 고정한다. `schedule.json`에는 JAR 해시·상한, `state.json`에는 완료/중단 내역, `measured-harness/`에는 실행한 도구 사본을 보존한다.
- 배치당 조회 60초, 5초 후 업로드, 업로드 관측 최대 50초. 측정 시작 25분 이후 새 배치를 시작하지 않고 30분 상한에서 종료한다. 도구 준비 시간은 별도다.
- k6는 일정 요청률의 HTTP 부하와 지연/오류/발행 누락, JDBC 계측은 획득/SQL/연결 점유, Hikari MXBean은 풀 상태, Python은 실행 순서·동일 결과 검증·집계를 담당한다. `ps`와 DB cgroup/`pg_stat_activity`로 다른 자원 한계를 함께 확인한다.
- 요청률별 결과는 별도로 집계한다. HTTP 오류나 부하 발행 실패는 사라지는 데이터가 아니라 보고할 결과이며, 지연 원인이 확인되지 않으면 DB 병목으로 단정하지 않는다.

측정 도구 검증: `python3 -m unittest discover -s scripts/performance -p 'test_*upload_query*.py'`. 로컬 macOS/Linux의 POSIX 타이머를 사용하며 제품 런타임 의존성은 추가하지 않는다.

### 관리자 1명 업로드 중 동시 조회 사용자 비교

[계획](../../docs/plans/2026-10-15-동시-사용자-조회와-업로드-트랜잭션-비교-계획.md)에 따라 기존 `upload_query_ramp.py`에 `--load-model users`를 지정한다. 풀 10개·업로드 worker 1개를 유지하고 VU 1 / 10 / 20 / 50 / 100명이 5초마다 함께 조회한다. 평균 목표 요청률은 각각 0.2 / 2 / 4 / 10 / 20건/초지만, 매번 VU 수만큼의 요청이 한꺼번에 시작되는 가정이다.

```bash
python3 scripts/performance/upload_query_ramp.py \
  --artifacts .local/performance/upload-query \
  --fixture-root .local/performance/upload \
  --output .local/performance/upload-query-users-NEW \
  --container kplasma-upload-benchmark-query-20261015 \
  --java /path/to/jdk-21/bin/java \
  --load-model users
```

기존 전용 벤치마크 DB, B/C 계측 JAR, seed와 인공 업로드 입력이 필요하다. 실행 중인 서버 포트나 기존 출력 폴더는 재사용하지 않는다. 사용자·제품 DB에 연결하지 않는다. `users` 모드는 조회 단독 실험을 실행하지 않는다. JVM 워밍업 업로드 3회를 제외하고 단계별 B/C 2회씩 총 20회 비교한다. 실제 제품 코드와 DB 설정은 변경하지 않는다.

- **k6:** `constant-vus`로 고정 VU를 실행하고 공통 시각 기준 5초 간격 조회. 요청별 VU·묶음 번호·예정 및 실제 시각·HTTP 시간·응답 해시 기록.
- **Python:** 동일 입력 업로드·seed 복원·실행 순서·시간 제한·결과 동등성 검증·클라이언트/서버 요청 ID 결합.
- **JDBC/Hikari 계측:** 연결 획득·점유 시간, SQL 실행 시간, 100ms 간격 active/idle/pending. 연결 획득 비용과 실제 대기열을 구분.
- **PostgreSQL/OS:** `pg_stat_statements`, `pg_stat_activity`, Java/k6 CPU·RSS와 Docker 자원 표본으로 다른 병목 확인.

기존 초당 요청률 실험은 `--load-model arrival`(기본값)로 유지한다. 두 방식의 지표를 같은 비교군으로 합치지 않는다. 각 요청이 늦어졌을 때 예정된 과거 요청을 연속해서 보충하지 않고 지난 구간을 건너뛰며, 실제 요청 수와 예상 횟수의 차이를 보고한다.

[실험 보고서](../../docs/verification/2026-10-15-동시-사용자-조회와-업로드-트랜잭션-비교.md). 관리자·업로드 worker를 함께 1 → 2 → 4 → 8로 늘리는 조건은 계획서의 후속 검토 범위이며 이번 측정과 구분한다.

### 발송 시각 통제 재검증

[기존 로그 감사와 재측정 결과](../../docs/verification/2026-10-16-조회-발송-시각-통제-재검증.md)를 함께 확인한다. `upload_worker_benchmark.py`의 `--workers`, `--repeats`, `--start-index`, `--restart-each-trial`로 범위·순서·예열을 고정한다. 기본 부하 도구는 k6다.

벽시계 변화에 영향받지 않는 로컬 비교에는 `--load-engine node-monotonic --upload-offset-ms 3000`을 사용한다. Node 기본 HTTP와 `performance.now()`로 100사용자/5초 동시 요청을 만들고, 같은 VU·회차는 같은 버전을 조회한다. HTTP 호출/쓰기 완료/응답 완료를 단조 시각으로 기록한다. 외부 의존성이나 제품 mock은 없다.

`analyze_upload_dispatch.py <결과경로> --workers 8 --same-vu --output <감사JSON>`은 발송 오차와 실제 업로드 중첩을 분리 검증한다. 1ms 해상도의 기존 `startEpochMs`는 패킷 송신 시각이 아니며, Node의 쓰기 완료도 커널 수신 증거는 아니다. 발송·처리 단계가 다른 시행을 제외할 때 원시 결과와 제외 사유를 보존한다. 도구를 바꾼 결과를 기존 k6 평균에 섞지 않는다.

## worker 8개 처리 시점 동기화 결과

[최종 보고서](../../docs/verification/2026-10-16-worker-8개-처리-시점-동기화-B-C-재측정.md)는 `--phase-gate`로 실제 파일 처리 신호에 맞춘 B/C 각 3회 전체를 집계한다. `analyze_upload_phase.py`의 `all_completed`를 대표값으로 사용하며, `phase_valid`는 이전의 엄격한 시점 기준에 대한 보조 진단이다. 원시 표본을 제외하거나 다시 측정하지 않고 집계 해석을 정리했다.

# 순방향 조회 성능 벤치마크

이 도구는 **격리된 인공 데이터**에서 A(전체 요약 + Python 선택), B(DB 조건 조회), C(기존 Run ID 기본 키 인덱스 조회)를 비교한다. 제품 조회 코드는 변경하지 않는다. B→C는 검색 키·접근 경로가 함께 바뀌므로 새 인덱스만 추가한 효과라고 해석하지 않는다.

## 실행 환경

- Java 21, 저장소 Gradle Wrapper, Docker Compose.
- macOS 또는 Linux에서 실행한다. 요청 제한 시간과 RSS 수집에 POSIX signal과 `ps`를 사용한다.
- `agent/python/uv.lock`에 맞춰 설치한 Python 3.12 또는 3.13 환경. `httpx`, `pytest`를 사용한다. `PYTHON`은 해당 환경의 실행 파일로 설정한다.
- 기본 실행은 서비스 `.env`를 읽지 않는다. 전용 DB명은 `forward_lookup_bench`, 컨테이너는 `kplasma-forward-benchmark-db`, 포트는 DB 15445 / Java 18085다. 같은 이름/포트의 다른 프로세스가 있으면 먼저 충돌을 해결한다.
- 전용 DB의 비밀번호와 worker token은 공개 가능한 로컬 테스트 값이다. 포트는 loopback에만 바인딩한다. 실제 서비스에 사용하지 않는다.

```sh
export JAVA_HOME=/path/to/jdk-21
export PYTHON=/path/to/python-environment/bin/python
docker compose -f scripts/performance/forward-lookup/compose.yaml up -d
mkdir -p .local/performance/forward-lookup
backend/gradlew -p backend --init-script ../scripts/performance/forward-lookup/benchmark.gradle forwardBenchmarkClasspath
```

처음 DB를 만들었으면 다음 서버 실행으로 Flyway 마이그레이션을 적용한 뒤 종료한다. 스키마 초기화가 끝나면 suite가 같은 서버를 필요할 때 실행·종료한다.

```sh
backend/gradlew -p backend --init-script ../scripts/performance/forward-lookup/benchmark.gradle forwardBenchmark
```

```sh
"$PYTHON" scripts/performance/forward-lookup/suite.py \
  --output .local/performance/forward-lookup/EXECUTION_ID
```

실행 디렉터리는 새 ID로 지정한다. 150 → 10,000 → 100,000 → 1,000,000 순서로 생성·측정한다. 생성기는 전용 컨테이너의 라벨·DB명을 검증한 다음 **그 DB의 이전 인공 데이터와 테스트 대화만 초기화**한다. 실제 업로드 API, 원본 파일, 서비스 DB는 사용하지 않는다.

`--sizes 150 10000`처럼 범위를 지정할 수 있다. 결과가 남은 디렉터리에서는 완료된 단계만 건너뛰며, 현재 DB 규모가 일치하지 않으면 재개하지 않는다. 실패·미완료 단계는 원자료를 보존하고 새 실행 ID에서 재측정한다. 숫자를 덮어쓰거나 실패한 실행을 성공으로 바꾸지 않는다.

A의 메모리 부족으로 JVM이 종료되면 그 직후의 B/C 접속 실패를 두 조회 전략의 성능으로 해석하지 않는다. 전체 실행이 끝난 뒤 같은 DB와 원본 `dataset.json`을 유지하고, 새 JVM·새 디렉터리에서 `run.py measure --methods b c --output ...`로 미측정 방식을 보충한다. 원 기록은 그대로 둔다. `report.py --supplement-root ...`는 같은 데이터·기준 커밋·런타임인 경우에만 합치며, 이미 측정된 방식의 표본을 덮어쓰거나 섞지 않는다.

## 측정 경계

| 단계 | 경로 | 반복 |
|---|---|---|
| M1 | 공통 projection의 실제 SQL `EXPLAIN ANALYZE, BUFFERS` | 방식별 대표 키 5개 |
| M2 | Python → Java/JDBC → HTTP JSON → 실제 `lookup_forward`·재검증 | 준비 5회 후 40개 입력 × 5라운드, 방식별 200회 |
| M3 | 실제 요청 제출·claim·LangGraph·checkpoint·manifest·답변 저장; 도구 선택 LLM만 고정 | 규모별 최대 10회, 각 빈 대화에서 시작 |
| 메모리 | 새 Java/Python 프로세스, 같은 준비 조회 후 RSS 100ms 샘플링 | 방식별 3회; M2 지연에 합치지 않음 |
| pgbench | 같은 SQL과 입력 목록, 1연결·1스레드·simple protocol | 방식별 60초 × 3회 |

- 실행은 순차적이다. 다른 벤치마크·개발 빌드·사용자 요청을 동시에 실행하면 자원 간섭으로 보고서에 기록한다.
- M2는 실제 네트워크·DB 시간을 측정한다. 가짜 저장 지연을 넣지 않는다. Java fetch 시간은 SQL·수신·매핑을 포함한다. 매핑은 그 안의 중첩 구간이다.
- 반환 후보 재계산뿐 아니라 독립 생성기 기대값으로 Run·버전·조건·수치를 검증한다. 불일치하면 즉시 중단한다.
- 요청 한도는 60초, M2 규모별 예산은 60분이다. 최초 timeout/전송 오류 후 해당 방식의 나머지 표본은 미완료로 남긴다. M3도 첫 실패 후 불필요한 같은 실패 반복을 멈춘다. 성공 표본 수와 실패·중단 이유를 함께 보고한다.
- M3는 실제 `run_claim`과 `DurableSaver`를 사용하며 테스트용 `Settings`로 외부 모델·Phoenix 연결을 비활성화한다. 로컬 span 이름·시간과 `BENCH_HTTP`의 SQL 횟수·JDBC execute 시간을 보관한다. 이는 Phoenix Cloud 업로드를 실행했다는 뜻이 아니다.
- pgbench는 DB 컨테이너 안에서 실행해 client↔DB의 호스트 네트워크 비용이 없다. 그 client CPU도 DB 컨테이너의 2 CPU 한도를 공유한다. M2와 같은 응답 경계가 아니다. [pgbench 공식 문서](https://www.postgresql.org/docs/18/pgbench.html)
- p95는 M2 원자료의 nearest-rank 방식이다. 실패는 따로 집계하며 완료 표본 p95로 성공률을 대신하지 않는다. M3 10회로 안정적인 p95나 최대 처리량을 주장하지 않는다.
- 저장 조건은 모두 적격·정규 단위의 인공 수치다. B SQL은 이 제한된 데이터에서의 비교용이다. 제품의 전역 제외 사유·근접 탐색·모든 비정상 JSON 정규화 구현을 대신하지 않는다.
- 원본 파형과 실제 `full_run` 크기를 재현하지 않는다. 1만 건 이상은 제품 파서의 조건 격자를 확장한 가정 상황이며 실제 물리 공정이나 등록 가능 용량을 뜻하지 않는다.

대표 요청의 Phoenix 흐름 확인은 주 측정이 끝난 뒤 별도 실행 디렉터리에서만 수행한다. 현재 DB와 일치하는 `dataset.json`을 사용하고 전용 Java 서버가 실행된 상태에서 다음 명령을 쓴다. 명시한 파일에서 Phoenix endpoint·key·project 세 항목만 설정에 반영하며 OpenAI 모델은 호출하지 않는다. 전송되는 값은 격리 DB의 인공 데이터다.

```sh
"$PYTHON" scripts/performance/forward-lookup/current_path.py \
  --output .local/performance/forward-lookup/DIAGNOSTIC_ID \
  --index 0 --phoenix-env /path/to/local/.env
```

이 진단 표본은 `phoenixEnabled=true`와 trace ID를 기록한다. Cloud에 실제 도착했는지는 별도로 확인하며 M2 또는 기본 M3 시간 통계에 합치지 않는다.

## 검증

```sh
PYTHONPATH=agent/python/src "$PYTHON" -m pytest scripts/performance/forward-lookup/tests -q
backend/gradlew -p backend test --tests '*ForwardLookupBenchmarkTest'
```

추가 회귀는 설계서의 `Verification Contract`를 따른다. 일반 CI에서 대량 성능 실행은 자동으로 시작되지 않는다. 벤치마크 서버·계측 클래스는 `src/test`에만 있고 제품 JAR에 포함되지 않는다.

## 결과와 다음 단계

실행 원자료와 로그는 `.local/performance/forward-lookup/EXECUTION_ID/`에 보관한다. Git에는 생성기·측정 코드·소량 테스트·집계 보고서만 올리고, 실제 데이터·대량 생성 데이터·DB 덤프·원시 로그·`docs/folio/`는 올리지 않는다.

```sh
"$PYTHON" scripts/performance/forward-lookup/report.py \
  --output .local/performance/forward-lookup/EXECUTION_ID
docker compose -f scripts/performance/forward-lookup/compose.yaml stop
```

집계는 같은 디렉터리의 `aggregate.md`와 `aggregate.json`에 저장한다. 종료 명령은 전용 DB 컨테이너만 멈추고 측정 원자료와 DB 볼륨을 보존한다.

DB 벤치마킹 완료 보고에서 **제품 변경 전 k6 기준 측정**을 반드시 제안한다. 기준 커밋과 입력·설정 식별값을 보관한 뒤 제품 개선을 별도 PR로 진행하고, 동일 k6 시나리오로 전후를 비교한다. M2의 개선율을 Agent 전체 응답 개선율로 표현하지 않는다.

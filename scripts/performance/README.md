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

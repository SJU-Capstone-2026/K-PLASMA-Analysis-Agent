# 순방향 정확 일치 조회: 제품 C 적용 및 Agent 실행 측정

측정일: 2026-10-11. 모든 데이터는 인공 데이터이며 실제 실험 결과가 아니다.

## 변경 범위

Python이 압력·소스·바이어스를 기존 단위 변환 규칙으로 정규화한 뒤 `forwardQuery`로 전송한다. Java는 조건으로 Run ID를 만들고 기존 `run_pkey` B-tree와 `current_version_id`를 사용해 현재 버전 한 건을 조회한다. 새 인덱스나 DB 마이그레이션은 추가하지 않았다.

조회한 Run의 실제 조건·단위·품질·수렴 상태를 확인한 후, 정확 일치할 때만 `manifest.runs`, `catalogRunRefs`, Python `source`를 한 건으로 제한한다. 체크포인트 기능과 최종 답변 저장은 유지한다. 재호출은 고정한 버전을 사용하며 다른 조건으로 바꿀 수 없다. 이어질문에서는 선택/기준 Run의 역사 버전을 먼저 읽고 조건을 계산한다.

조건을 정수 Run ID로 정확하게 표현할 수 없거나, 해당 Run이 없거나, 상태·실제 조건이 다르면 기존 전체 목록 기반 근접 Run 조회를 유지한다. 이 경로의 대규모 성능 문제는 이번 최적화 범위 밖이다. 정확 일치 결과의 `excludedRuns`에는 조회와 무관한 다른 Run의 제외 사유를 열거하지 않는다. 기존에 고정한 전체 manifest는 최신 값으로 덮어쓰지 않는다.

Java와 Python을 함께 배포해야 한다. 새 worker는 `forwardQuery`를 사용하고 기본 graph build ID도 변경했다. 별도로 `AGENT_GRAPH_BUILD_ID`를 지정한 환경에서는 새 배포 ID를 지정해야 한다. 기존 진행 중 요청은 버전 검증 때문에 재시작이 필요할 수 있다.

## 비교 방법

- A는 [기존 벤치마크 PR #15](https://github.com/SJU-Capstone-2026/K-PLASMA-Analysis-Agent/pull/15)의 M3 원본 기록을 재사용했다. A 재실행은 하지 않았다.
- 기준 커밋은 `fe8463e5c7dbe3ed2919bb43bad850f3292906c9`, 제품 기반은 동일한 `main`의 `bbe01be`이다. C에서는 실제 제품 Java/Python 클래스를 실행했다.
- 150 / 1만 / 10만 / 100만 건, 규모별 동일 입력 10개를 순차 실행했다. seed `20261010`, 데이터 집합 해시와 40개 입력 corpus를 기존 기록과 대조했다. 동일 조건의 현재 Run은 하나이고 버전은 별도 참조한다.
- 기존 A와 동일하게 요청마다 새 Java·Python 프로세스와 빈 대화를 사용했다. DB 준비·대화 초기화·서버 부팅은 측정에서 제외했다.
- 측정 구간: 요청 제출 → claim → LangGraph → 조회·계산·검증 → 동기 체크포인트 → 최종 답변 저장 → 완료 응답 확인.
- **LLM 도구 선택만 기존 A와 같은 고정 응답으로 대체했다. 아래 수치는 실제 LLM 응답 지연·프론트 화면 표시·worker polling 대기를 포함하지 않는다.** k6 동시 부하 테스트도 아니다.
- Postgres 18.6 / Docker 2 CPU·3 GiB / shared_buffers 256 MB / work_mem 16 MB / 병렬 조회 0. Java 21.0.12 / Xms256m·Xmx4g / pool 2 / prepareThreshold 0. Python 3.12.15. 같은 로컬 Mac에서 측정했다.
- 10개 표본과 날짜가 다른 기존 A를 비교하므로 전용 서버에서의 통계적 성능 보장이나 서비스 전체 지연 개선율로 일반화하지 않는다.

## Agent 완료 시간

| 규모 | 기존 A | 제품 C 평균 | C 최솟값–최댓값 | 완료 |
|---|---|---:|---:|---:|
| 150건 | 평균 448.52ms | 231.43ms | 209.57–256.69ms | 10/10 |
| 1만 건 | 체크포인트 크기 제한으로 실패 | 228.67ms | 220.14–246.58ms | 10/10 |
| 10만 건 | 체크포인트 JSON 크기 제한으로 실패 | 233.44ms | 216.13–255.82ms | 10/10 |
| 100만 건 | context 시간 초과·Java OOM | 242.20ms | 218.70–270.49ms | 10/10 |

150건의 평균 완료 시간은 **217.09ms, 48.40% 감소**했다. 1만 건 이상은 A가 완료하지 못했으므로 완료 시간 단축률을 계산하지 않는다. C는 네 규모에서 40/40회 완료했고, Run ID·버전·세 결과 지표가 독립 생성 기준과 일치했다.

## 구간별 결과

150건, 각 요청의 해당 span 시간을 합한 뒤 10회 평균을 냈다.

| 구간 | A | C |
|---|---:|---:|
| context 요청·응답 | 36.46ms | 10.26ms |
| calculate 노드 | 22.40ms | 7.48ms |
| validate_result 노드 | 16.00ms | 7.54ms |
| 체크포인트 저장 합계 | 231.58ms | 90.39ms |
| 최종 답변 저장 | 26.25ms | 20.31ms |

목록 전달·Python 순회뿐 아니라 중간 저장 크기도 줄면서 효과가 났다. 각 규모의 대표 요청에서 HTTP 29회, SQL 164회를 관측했다. 기존 A는 SQL 165회였다. 대부분은 단계·권한·상태 검증과 저장이며, 이번 개선을 N+1 해소나 SQL 횟수 대폭 감소로 설명하면 안 된다.

`graph.gather`에는 `backend.context`가 포함되므로 중첩 span을 더해 전체 시간으로 계산하지 않는다. 체크포인트 시간은 저장 15회의 합계다.

## 상태 크기와 안정성

40회 모두 `manifest.runs`와 `catalogRunRefs`가 각각 한 건이었다. Python은 해당 `runs`를 `source`로 사용한다. manifest는 최대 1,763바이트, 마지막 체크포인트는 최대 65,102바이트로 관측됐다. 100만 건에서도 전체 목록을 전송·저장하지 않았다.

100만 건에서 제품과 동일한 SQL의 `EXPLAIN (ANALYZE, BUFFERS)`는 `run_pkey`와 `run_version_pkey`의 Index Scan, 각각 actual rows 1을 확인했다. 이 별도 진단의 실행 시간은 0.116ms이며 Agent 전체 시간과 섞지 않았다.

크기는 측정 후 Python JSON 직렬화로 계산한 UTF-8 바이트이며 PostgreSQL 디스크 점유량이나 전체 HTTP 송수신량이 아니다. 완료 시 manifest와 checkpoint가 정상 정리되므로, 실행 중 객체 참조를 보관하고 시간 측정이 끝난 후 크기를 계산했다.

초기 계측 준비 실행에서 제품 요청은 완료했지만 완료 후 삭제된 DB checkpoint를 읽으려던 진단 코드가 실패했다. 그 기록은 보존하고 통계에서 제외했다. 최종 측정은 수정한 동일 계측기로 별도 디렉터리에 기록했다.

## 실제 LLM 연결 확인

100만 건 인공 데이터에 대해 “압력 8 mTorr 소스 300 W 바이어스 600 W 조회”를 실제 `gpt-5.6-luna`, 추론 `none`으로 한 번 실행했다. 최종 제품 빌드에서 성공했고 실제 조건·버전·결과 지표가 맞았다. 조회·고정 목록은 각각 한 건이었다.

- 요청 제출부터 완료 확인: **3,694.33ms**.
- LLM 도구 선택 span: **3,409.73ms**.
- context 요청·응답: **12.63ms**.
- 모델 호출 1회, 입력 2,013토큰·출력 58토큰. 고정 모델 측정 40회에서는 외부 LLM 호출이 없다.
- Phoenix Cloud REST 조회로 27개 span 도착, 모두 `OK`, 모두 `benchmark.synthetic=true` 확인.
- trace: `57d47376c0aabfdc15968a4ccc289a73`.

이는 연결·처리 성공을 확인한 단일 진단이다. 기존 A의 실제 LLM 측정이 없으므로 **실제 LLM을 포함한 전체 응답이 48.4% 빨라졌다고 주장하지 않는다.** 모델 지연을 포함한 전후 분포·동시 처리량은 별도 k6 범위다.

## 재현

기존 PR #15 커밋을 별도 checkout에 준비한다. 실제 서비스 DB를 사용하는 명령으로 변경하지 않는다. 전용 `kplasma-forward-benchmark-db`는 이름·라벨·DB 이름을 검사한 뒤 인공 데이터만 초기화한다.

```bash
export FORWARD_BENCHMARK_ROOT=/path/to/benchmark-checkout
export FORWARD_AGENT_CLASSPATH=/tmp/kplasma-forward-agent/classpath.txt
docker compose -f "$FORWARD_BENCHMARK_ROOT/scripts/performance/forward-lookup/compose.yaml" up -d
backend/gradlew -p backend -I "$PWD/scripts/performance/forward-agent.gradle" forwardAgentClasspath
uv run --project agent/python --frozen python scripts/performance/forward-agent.py \
  --benchmark-root "$FORWARD_BENCHMARK_ROOT" \
  --classpath "$FORWARD_AGENT_CLASSPATH" \
  --output "$FORWARD_BENCHMARK_ROOT/.local/performance/forward-lookup/product-c-new"
```

이전 A의 `.local/performance/forward-lookup/run-20261010/<규모>/dataset.json`이 필요하다. 원본 로그·데이터는 Git에 넣지 않는다. `forward-agent.gradle`은 테스트 classpath만 확장하며 제품 bootJar에 벤치마크 API를 넣지 않는다.

## 검증

- 변경 전 새 Java 회귀 테스트 6개 중 3개가 예상대로 실패했다. 수정 후 통과했다.
- Python: `pytest agent/python/tests agent/python/evals -q` — 341개 통과.
- Python `ruff check`, `mypy agent/python/src` — 통과.
- Java `./gradlew test --console=plain` — 159개 통과. 리뷰 후 재조회 참조 추가 경로와 기존 manifest 보존 테스트를 보강했고 `ForwardQueryContextTest` 8개도 통과했다. 최초 조회 측정 경로는 바뀌지 않았으며 최종 빌드는 위 실제 LLM 진단에서 다시 확인했다.
- `node scripts/verify-public-files.mjs`, `git diff --check` — 통과.

코드 리뷰는 사용자의 단독 작업 지시에 따라 직접 수행했다. 참조 추가·재호출·이전 manifest 재사용·단위 정규화·0·조회 실패 시 근접 Run 경로를 확인했다.

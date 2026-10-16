# 역방향 조회 A/B/C 벤치마크

실제 서비스 `.env`나 DB를 사용하지 않는다. 전용 container label과 DB 이름을 확인하며, seed는 이 DB만 초기화한다. 원시 출력은 `.local/performance/reverse-lookup/`에 저장한다.

- A: 제품 변경 전 main commit `bbe01beb`의 Java 실행 파일·Python 소스를 보존해 실행한다.
- B/C: 같은 개선 코드와 인공 데이터. B는 Flyway target 6, C는 target 7의 인덱스만 추가한다.
- Java 테스트 전용 `ReverseLookupBenchmarkSupport`가 실제 `ReverseContextQuery`를 호출한다. 도구 선택과 SQL을 흉내 낸 별도 쿼리를 사용하지 않는다.
- `/benchmark/query` 시간은 인벤토리·실제 검색 SQL·응답 생성 경계다. manifest 저장을 포함한 실제 context API와 Agent 전체 시간은 `current_path.py`에서 측정한다.
- `/benchmark/explain`은 바인딩된 실제 검색 SQL의 실행 계획이다. JDBC execute 시간과 EXPLAIN 시간은 서로 다른 측정값이다.
- 고정 결과는 에너지 150~160 eV의 5건이며, 규모가 바뀌어도 수치·버전·순서는 같다. 인공 공정 조건은 고유하다.
- Agent 실행은 LLM tool selection만 고정하며 실제 Python LangGraph·Spring HTTP·DB 저장을 사용한다. 실제 LLM 전체 응답 속도라고 표현하지 않는다.

## 실행

Java 21과 프로젝트 Python 환경, Docker를 준비한다. 먼저 A 기준선 checkout에서 같은 테스트 서버와 측정 도구를 사용해 컴파일·측정하고 코드/실행 파일을 보존한다.

```sh
docker compose -f scripts/performance/reverse-lookup/compose.yaml up -d
JAVA_HOME=<Java21> backend/gradlew -p backend -I scripts/performance/reverse-lookup/benchmark.gradle reverseBenchmarkClasspath
# 생성된 .local/performance/reverse-lookup/classpath.txt로 테스트 서버를 시작한다.
java -Xms256m -Xmx4g -Dbenchmark.flyway-target=6 -cp '<classpath>' com.kplasma.analysisagent.agent.ReverseLookupBenchmarkSupport
python scripts/performance/reverse-lookup/run.py --size 150 --method b --output .local/performance/reverse-lookup/b/150
python scripts/performance/reverse-lookup/current_path.py --index 0 --output .local/performance/reverse-lookup/b/150
```

규모는 150, 10000, 100000, 1000000이다. 쿼리는 워밍업 5회 이후 200회, Agent는 전후 각 10회다. 실패 후 무조건 반복하지 않고 오류·단계를 보존한다. 결과 폴더를 덮어쓰지 않는다. A의 실패 표본에는 개선율을 계산하지 않는다.

B/C를 번갈아 비교할 때 인덱스의 제거·재생성은 반드시 이 표시된 벤치마크 DB에서만 수행한다. 두 비교군에 같은 통계 갱신과 워밍업을 적용한다. 일반 제품 DB에서 Flyway target을 변경하거나 인덱스를 제거하는 실행 방법이 아니다.

실제 API·브라우저 부하 검증(k6)은 DB 결과 확인 후의 후속 범위이며, A 런타임을 보존해 이전 baseline을 재실행할 수 있게 한다.

## 추가 정확성·DB 검증

- `normalization.py`: 현재 Python 정규화와 V6의 SQL 함수를 1,870개 인공 입력에서 대조한다. 반드시 이 벤치마크 DB에 V6 이후를 적용한 뒤 실행한다.
- `scenarios.py`: 100만 건 fixture의 Q2/Q3/Q4/Q5/Q6를 독립 수학식으로 생성한 전체 기대 집합과 비교한다. `seed.py --size 1000000` 실행 뒤 사용한다. 파일의 기본 규모는 100만 건이다.
- `JAVA_HOME=<Java21> python scripts/performance/reverse-lookup/pgbench.py`: 같은 100만 건에서 실제 제품 SQL을 테스트 main의 `--dump-query-sql`로 생성하고 C/B/B/C 각 100회, 워밍업 각 5회 반복한다. **표시된 벤치마크 DB의 검색 인덱스를 제거·재생성한다.** 기록된 결과를 덮어쓰지 않는다. Java 테스트 classpath를 먼저 다시 생성한다.
- `current_path.py --scenario no_match|independent`: 별도로 seed한 150건에서 공통 0건·개별 조건 탭의 실제 Agent 저장 경로를 검증한다. 일반 `match`와 결과 폴더를 구분한다.
- `report.py --root .local/performance/reverse-lookup`: A/B2/C 원시 파일로부터 성공 평균을 산출한다. B2는 final VACUUM 절차를 동일하게 적용해 재측정한 B를 뜻한다. 초기 B 탐색 결과를 평균에 섞지 않는다.

실측 요약·실패·범위 제한은 [검증 보고서](../../../docs/verification/2026-10-15-역방향-조회-성능-개선.md)에 있다. 원시 데이터·실행 파일·화면은 Git에서 제외한다.

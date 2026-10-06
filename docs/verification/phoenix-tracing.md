# Phoenix Cloud 추적 검증

2026-10-06 사용자 요청으로 Graph v1의 실행과 응답을 개인 Phoenix Cloud의 지정 프로젝트에서 관찰하도록 추가했다. 전체 노드 상태와 LLM 입출력을 포함하며 키·내부 인증 토큰은 제외한다. 실험 데이터를 생성하거나 질문 해석·수치·Run 버전·UI·checkpoint 계약을 바꾸지 않는다.

## 실행 경계

- 한 claim은 `agent.request` trace, 요청 ID는 `session.id`다. 추가 입력과 worker 재시작은 같은 session의 다음 trace이며 generation/revision과 resumed를 기록한다.
- 노드별 JSON 입력·출력, 경로, 도구, 결과 상태와 후보 개수, 실제 LLM 입력·원문 출력·스키마 검증·토큰 수를 수집한다. backend 조회·checkpoint 존재/버전·저장·최종 게시도 수집한다. opaque saver와 heartbeat polling은 제외한다.
- Phoenix 설정은 복구 fingerprint에서 제외한다. 전송은 SDK의 HTTP/protobuf batch이며, 관찰의 예외가 실행을 재시도하거나 실행의 예외를 삼키지 않는다. 원격 장애나 SIGKILL에서는 추적 유실이 가능하며 실행 복구는 PostgreSQL이 담당한다.
- tracing extra에 `arize-phoenix-otel`을 잠갔다. SDK 자동 계측 대신 명시적 span을 사용해 SDK 오류 본문·HTTP 인증 헤더가 수집되지 않게 한다. 기존 미사용 OpenAI 자동 계측 의존성은 제거했다. CI는 tracing extra를 설치해 관찰 테스트를 포함한다.

## 검증 기록

- 구현 전 `test_tracing.py`는 tracing 모듈 부재로 수집 실패했다. 상태와 수치를 바꾸지 않는 관찰, 비밀값 제외, 전송/등록 예외 격리, 추가 입력과 재개를 검증하는 테스트를 먼저 작성했다.
- 최초 LLM span 테스트 fixture는 SDK 응답의 필수 필드가 부족해 실패했고 fixture를 수정했다. 제품의 오류를 테스트 통과로 감추지 않았다.
- `agent/python/.venv/bin/python -m pytest agent/python/tests agent/python/evals -q`: 194개 통과. 기존 수치·그래프·checkpoint 복구 검증을 포함한다.
- 잘못된 IPv6 URL의 parser 예외가 worker 시작을 중단하는 경계와 error status description의 비밀값 제외 누락을 각각 실패 테스트로 확인한 뒤 수정했다.
- Ruff/Mypy와 전체 Node typecheck/ESLint 통과. 실제 OpenTelemetry SDK의 in-memory exporter로 원문 JSON·0/누락 구분·긴 필드·키 제외·parent/session·오류 상태·재개·LLM 원문/스키마/토큰을 확인했다. 실제 SDK batch exporter를 timeout 없이 Event로 막고, 전송 해제 전에 별도 실행 thread의 입력 대기 완료를 확인했다. 이어진 재개·최종 완료와 모델 호출 한 번도 유지됐다. 전송은 해제 후 FAILURE를 반환했다.
- 지정 Phoenix Cloud의 인증과 프로젝트 이름을 REST API로 확인했다. 실험 데이터와 사용자 DB를 사용하지 않고 일반 개념 질문 한 건에 실제 `gpt-5.6-luna` / `none`을 호출했다. 결과는 `CONCEPT_READY`, 실행 오류는 없었다.
- batch flush 후 Cloud REST API에서 `agent.request`, 5개 그래프 노드와 LLM 2개, 총 8개 span의 같은 session과 parent 관계 및 입력/출력·버전·사용량 필드를 확인했다. 이 실행의 backend/checkpoint는 테스트용 메모리 구현이었다. 실제 사용자 DB 전체 흐름이나 실험 데이터로 다섯 도구를 Cloud에서 재검증한 것은 아니다.
- 정상 종료 시에는 `force_flush(timeout_millis=3000)` 요청 뒤 SDK shutdown을 수행한다. 잠근 SDK는 이 timeout 인자를 실제 3초 종료 기한으로 보장하지 않으며, 진행 중인 export와 재시도 때문에 프로세스 종료가 더 늦어질 수 있다. 이 대기는 분석의 요청 완료 뒤이며 복구·결과 저장 기준을 바꾸지 않는다.
- 실제 클라우드 장애·강제 종료 시 추적 보존, Phoenix UI의 전체 화면 비교는 이번 검증에 포함하지 않았다. 연결 정보와 원문 모델 응답·trace는 Git에 저장하지 않는다.

# Docker VM 3GiB 적용과 v2_localLLM 웹 5문항 검증

2026-11-13, Apple M4 Pro / 통합 메모리24GiB. 사용자의 3GiB 지정에 따라 Docker VM 메모리만 변경했다.
DB 검사와 새 전체 스택 인공 메모리 검사를 통과한 뒤 Q01~Q05를 웹에서 각1회 실행했다.
**웹 자동 정답5/5·자동 UI 검사5/5, 추가 swap0, 관측 critical0**이다. 실행 중 warning은 남아 있다.

## 적용한 설정과 보존 범위

- Docker Desktop4.45.0의 Resources → Advanced에서 memory slider를8092MiB에서3072MiB로 변경하고 Apply & restart했다.
- CPU12·Docker swap1024MiB·디스크·네트워크 설정은 변경하지 않았다. 종료 후 공식 settings-store의 `MemoryMiB=3072`도 확인했다.
- 재시작 후 엔진 `MemTotal`은3,054,383,104bytes(약2.845GiB)였다. 설정한3GiB와 게스트에서 보고하는 사용 가능 총량은 구분한다.
- Qwen3.5-9B GGUF Q4_K_M / llama.cpp b12317 Metal, context24,576, batch/ubatch256/256을 유지했다.
- d1-2B Q8_0 / context32K / batch·ubatch16,000, 계획 검토ON을 유지했다. 기존처럼 큰 모델 버퍼는 순차 상주한다.
- 입력16K·계획 출력6,000·답변3,000·생각 예산2,048·호출 제한90초·재계획 최대2회·답변 재작성 최대1회를 유지했다.
- 그래프·도구·native `submit_plan` 필드·최종 응답 계약·준비 판정 기준을 변경하지 않았다. 제품 코드 수정은 없다.

## DB 검사

원본은150 Run/150 version이며 읽기 전용 트랜잭션으로 목록·카탈로그·상세 조회만 수행했다.
복원은 동일 이미지·주요 메모리 설정의 새 격리 사본에 기존150 Run 백업을 적용했다.
이 사본은 원본과 파일 단위로 동일한 DB라는 뜻이 아니다. 쿼리 결과는 폐기하고 자원 카운터만 저장했다.

| 단계 | 표본 최대 working set | 해당 컨테이너 시작 후 캐시 포함 커널 피크 |
| --- | ---: | ---: |
| 원본 대기 | 70.52MiB | 77.43MiB |
| 원본 동시 조회4개 | 221.14MiB | 518.58MiB |
| 사본 복원 | 316.41MiB | 1057.12MiB |
| 사본 동시 조회4개 | 375.50MiB | 1398.41MiB |
| 사본 동시 조회10개 | 587.05MiB | 1647.00MiB(1.608GiB) |

DB 검사125개 표본은 모두 정상 압력이었다. 원본Run/version 수를 재확인했고 검사 사본과 그 anonymous volume만 제거했다.
원본 DB는 exit0으로 정상 정지해 시작 전 상태로 복구했다.

working set은 Linux Docker CLI와 같은 `memory.current - inactive_file` 값이다.
약1초 표본의 최대는 순간 최대와 다르다. `memory.peak`는 표본 사이의 짧은 피크와 캐시도 포함한다.
컨테이너 안에서 실행한 psql·계측 명령의 메모리도 포함된다.
[Docker stats의 메모리·캐시 계산](https://docs.docker.com/reference/cli/docker/container/stats/).

## 새 인공 메모리 준비 검사

DB·백엔드·웹·브라우저와 Qwen/d1을 띄운 별도 인공 스택에서 기존7행 검사를 재실행했다.
Qwen writer와 d1 각각 입력256/4096/15500 목표6행, 장문 native planner 생각ON1행이 모두 통과했다.
실제 tokenizer count와 usage가 일치했고 writer 생각OFF·planner 생각ON도 확인했다.
97개 준비 검사 표본 전부 정상, 추가 swap0, 기존 resident 계산 지표 최대19.666GiB였다.
가장 긴 개별 행은61.446초로 기존90초 한도 안이었다. 새 증거를 기존 `verify_memory_report`로 검증한 뒤 웹 평가 워커에 공급했다.

## 웹 Q01~Q05

원래150 Run frozen bundle과 문항 은행을 사용했다. 은행 SHA-256은
`3e4648ad1ee51f952a212d859369c7c8a764ad77e3587f15b37a9fea32ed0e9c`이며 원본 문항·정답·grader는 바꾸지 않았다.

| 문항 | 최초 계획 즉시 채택 | 재계획 | d1 계획 검토 | 자동 정답 | 자동 UI 검사 | 시나리오 시간 |
| --- | --- | ---: | --- | --- | --- | ---: |
| Q01 | 아니오 | 1 | PASS | 통과 | 통과 | 150.427초 |
| Q02 | 아니오 | 1 | PASS | 통과 | 통과 | 122.796초 |
| Q03 | 아니오 | 1 | PASS | 통과 | 통과 | 119.556초 |
| Q04 | 예 | 0 | PASS | 통과 | 통과 | 66.918초 |
| Q05 | 예 | 0 | PASS | 통과 | 통과 | 73.766초 |

시간은 브라우저·워커 준비·대기까지 포함하며 순수 추론 시간이 아니다.
서로 다른 웹 요청5개, API 모드 접수0개, 여섯 번째 문항0개를 확인했다. 새 trial 재접수는 없다.
모델 계획8회는 모두 원래 PlanDraft schema를 통과했다. 최초 계획 즉시 채택2/5, 재계획 후 통과3/5다.
d1 PLAN_REVIEW 실제5회가 모두PASS였으며 d1의 잘못된 계획 거부 능력까지 검증한 결과는 아니다.

390/800/1008/1440px의 자동 UI 검사는5문항 모두 통과했다. 수동으로 Q03 desktop과 Q01 mobile 캡처도 확인했다.
Q03은 기존과 같이 없는 IED width를 `—`로 표시하고 결측 사유를 충분히 설명하지 않는다. 기존 수동 검토 표시를 유지한다.
Q01 mobile 표에는 긴 Run명·단위의 줄바꿈이 많아 가독성 한계가 있다. 자동 UI 통과를 완전한 수동 품질 승인으로 확대하지 않는다.
이번에는 응답/UI 보존 범위에 따라 이를 수정하지 않았다.

## 최대 피크와 메모리 압력 기록

각 행은 서로 다른 지표의 독립 최대이며 더해서 고유 물리 메모리 총량으로 계산하면 안 된다.

| 대상·지표 | 최대 관측값 |
| --- | ---: |
| DB 별도 부하 검사, 캐시 포함 커널 피크 | 1.608GiB |
| 웹 평가 DB, 캐시 포함 커널 피크 | 1.060GiB |
| 웹 평가 DB, working set 표본 최대 | 336.22MiB |
| Docker VM 프로세스, 호스트 footprint 표본 최대 | 3.006GiB |
| Docker VM 프로세스, 호스트 RSS 표본 최대 | 4.560GiB |
| Qwen 프로세스, RSS 표본 최대 | 6.643GiB |
| d1 프로세스, RSS 표본 최대 | 3.833GiB |
| Mac 전체, 기존 resident 계산 지표 표본 최대 | 19.942GiB |

Mac resident 지표는 `vm_stat`의 active·wired·compressor 페이지 합계다. 모든 RAM의 완전한 분해나 모델 전용 RAM이 아니다.
그 최대는19:06:23 KST에 관측했다. footprint는 압축분을 포함한 프로세스 회계이고 RSS는 공유 매핑 등을 포함할 수 있다.
Docker의3GiB는 Linux VM의 RAM 배정 설정이며, 호스트 Docker 프로세스 RSS의3GiB 상한을 뜻하지 않는다.
실제로 RSS4.560GiB가 관측됐으므로 이를3GiB 미만으로 보고하거나 고정 VM 오버헤드로 역산하지 않는다.
[Docker VM 자원 설정](https://docs.docker.com/desktop/settings-and-maintenance/settings/).

Qwen 시작 전부터 인공 검사·웹 스택 준비·웹5문항·소유 서비스 정리까지 약852.8초, 총919개 표본을 수집했다.
정상745·warning174·critical0이고 이 구간의 추가 swap은0이다.
웹 단계만 보면673개 표본 중 정상499·warning174·critical0이다. 가장 긴 관측 연속 warning 구간은 약79.85초였다.
인공/웹 DB의 `memory.events`는 oom/oom_kill0, 컨테이너 OOMKilled=false였다.
warning을 정상으로 바꾸거나 준비·중단 기준을 완화하지 않았다.

DB·인공 검사를 통과하고 웹 평가를 완료했지만 **메모리 경고가 해소되거나 상시 운영에 충분한 여유가 입증된 것은 아니다.**
전 시도와는 계측 간격·측정 구간·다른 앱의 활동도 달라 이 결과만으로 개선 폭 전부를3GiB 설정의 인과 효과라고 단정하지 않는다.
전체40문항·장시간 동시 사용·상용v2와의 품질 동등성은 이번 범위가 아니다.

## 검증과 정리

- 기존 `db/measure.py`를 비공개 복사본에서 재사용해 원본 읽기 전용·사본 복원·동시 조회를 측정했고 exit0이었다.
- `node -- scripts/agent/measure-local-llm.mjs --env-file <private-profile>`와 같은 기존 검사 본체로 새 전체 스택 증거를 만들었다.
- 기존 `evals.run_flow --live --graph-version v2_localLLM --mode browser --limit 5` 본체로 실행했고 exit0이었다.
- 원래보호 대상 그래프 소스49개 hash, PlanDraft·submit_plan schema와 runtime_profile 불변을 재확인했다. 제품 코드 수정이 없어 전체 소프트웨어 단위 테스트는 재실행하지 않았다.
- 새 메모리 증거를 `verify_memory_report`로 다시 검증했고 Docker 종료 후에도 `MemoryMiB=3072`가 유지됨을 확인했다.
- 소유 Qwen·격리 DB·백엔드·웹·브라우저를 정리했다. Docker도 정상 종료했고 기존 d1은 sleep 상태로 유지했다. 다른 앱은 종료하지 않았다.
- 실제 답변·화면·질문·DB·모델 원문·시점별 카운터는 Git 밖의 비공개 경로에 보존했다. 활성 앱의 private 실행 프로필 승격, commit/push/PR은 하지 않았다.

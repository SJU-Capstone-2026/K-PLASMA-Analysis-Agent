# V2 평가 실행

Decisions 단독 평가는 고정 계획의 의미 판별을, 회귀 테스트는 모델이 직접 계획을 만드는 웹·API 흐름을 검사한다.
자동개선 테스트셋은 일반 V2의 최초 계획을 API에서 독립 정답표로 채점한다.
실제 모델 평가는 각각 별도 수동 명령으로 실행한다.

[3회차 평가 기록](../verification/2026-11-11-agent-v2-round3.md)에 웹 39/40·API 37/40·Decisions 80/80과 실제 평가 조건을 기록했다.
아래 명령과 결과는 표준 V2 기준이다. 로컬 모델은 [LocalLLM 실행 가이드](agent-v2-local-llm.md)를 따른다.

| 평가 | 기본 실행량 | 범위 | 외부 준비물 |
| --- | --- | --- | --- |
| Decisions 단독 | 80회: 정상 40 / 오류 40 | 원문과 고정 계획의 의미 일치 판별 | 모델 키 |
| 회귀 테스트 | 고정 40문항을 웹·API에서 각각 실행 | 계획 → 검토 → 도구·HITL → 필요한 답변·검토·수정 → 저장 | 모델 키, 비공개 고정 문항·정답 묶음, 격리 DB·backend·frontend |
| 자동개선 테스트셋 | 학습용 100문항 또는 평가용 50문항 | 최초 계획의 대상·조건·사용자 확인·단계 연결 검사 | 모델 키, 비공개 자동개선 문항·정답, 동결 Run 묶음, 격리 DB·backend |

질문 80개는 모델 API 호출 80번이라는 뜻이 아니다. 계획·Decisions·재계획·답변 작성 등
요청 내부 호출도 비용에 포함된다. 실패 문항의 추가 유료 재실행은 자동으로 하지 않는다.

## 공통 준비

저장소 루트에서 잠금 파일에 맞는 Node/npm, Python/uv 환경을 준비한다.
전체 흐름에는 JDK 21, Docker PostgreSQL, Playwright Chromium도 필요하다.

```sh
npm ci
uv sync --project agent/python --frozen --extra tracing
uv run --project agent/python --frozen python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
npm exec --workspace frontend -- playwright install chromium
```

키는 Git 밖의 로컬 env 파일에 둔다. 아래 비밀값 자리는 직접 설정한다.

```dotenv
OPENAI_API_KEY=<private-key>
AGENT_V2_PLAN_MODEL=gpt-6-luna
AGENT_V2_PLAN_REASONING_EFFORT=low
AGENT_V2_ANSWER_MODEL=gpt-6-luna
AGENT_V2_ANSWER_REASONING_EFFORT=low
AGENT_V2_DECISIONS_MODEL=gpt-6-luna
AGENT_V2_PLAN_REVIEW_ENABLED=true
AGENT_MODEL_TIMEOUT_SECONDS=90
```

실제 Agent 평가는 계획 의미 검토를 켠다. 설정이 꺼져 있으면 시작을 거부한다.
새 요청의 그래프 상태도 활성 설정으로 초기화되며, 스키마 2의 순수 개념 계획을 포함해 실행할 계획에는
`PLAN_REVIEW` 기록이 있는지 추가로 확인한다. 재계획 최대 2회, 필요한 답변 검토와
재작성 최대 1회는 유지한다. 모델 호출 timeout 90초는 질문 전체 제한과 별도다.

## 1. Decisions 단독 80회

저장소 루트에서 다음 명령을 직접 실행하면 유료 API를 호출한다.

```sh
npm run eval:decisions:local -- --env-file /path/to/eval.env --output /tmp/decisions-run-001
```

기존 13쌍의 정상·오류 계획을 3번씩 검사한 78회에 14번째 쌍을 한 번씩 추가한다.
서로 다른 계획은 28개이고 호출 수는 80회다. 모두 인공 입력이며 planner, DB,
backend, 브라우저를 시작하지 않는다. 정답은 Decisions 응답에서 만들지 않는다.

비용 없이 목록만 확인하려면 `agent/python`에서 다음을 실행한다.

```sh
uv run --frozen python -m evals.run_plan_review --output /tmp/decisions-plan-001
```

유료 실행 후 출력 폴더의 `results.jsonl`과 `summary.json`을 읽는다.
정상 계획을 거절한 경우, 오류 계획을 승인한 경우, 판정 불가와 API 오류를 구분한다.
각 실험에는 새로운 출력 경로를 사용해 이전 결과를 보존한다.

## 2. 회귀 테스트 · 기존 40문항

`eval:agent:local -- --suite regression`은 같은 40문항을 먼저 실제 브라우저에서 한 번씩,
다음으로 실제 backend API에서 한 번씩 실행한다. 메모리 그래프로 대체하지 않는다.
브라우저는 실제 입력·버튼·선택창을 조작하고, API는 미리 정한 사용자 선택을
실제 `NEEDS_INPUT`·선택지·revision에 맞춰 같은 요청의 resume API로 전달한다.

**입력 데이터.** Git 밖의 비공개 묶음 디렉터리에 다음 파일을 준비한다.
이미 사용한 동결 문항과 독립 정답을 그대로 재사용하며 임의로 최신 데이터에서
정답을 다시 생성하지 않는다. 이 자료는 저장소나 PR artifact에 포함하지 않는다.

| 파일 | 역할 |
| --- | --- |
| `cases.json` | 고정 40문항, 선택 Run·기준, HITL 선택, 기대 필터·정렬·수치·정답 집합과 검토 기준 |
| `runs.json` | 고정 Run의 불변 버전, 조건, 수치, 단위·분석 메타데이터. 기존 묶음은 149개, 복원 후 별도 묶음은 150개 |
| `wave-expected.json` | 원본 파형에서 독립 계산한 기대값 |
| `distribution-expected.json` | 원본 분포에서 독립 계산한 기대값·부재 이유 |
| `oracle-overrides.json` | 해당 oracle 해시와 일치하는 동결 정답 보정이 있는 경우 함께 공급 |

실행기는 문항별 oracle 해시, 40개 고유 문항과 범주 구성, 기대 검색 결과·계산을
확인한다. 다른 자료나 잘못된 정답 묶음을 사용하면 사전 검사에서 중단한다.
새 문항을 추가하는 실험은 기존 기준을 덮어쓰지 말고 별도 버전으로 준비한다.
Run 수는 각 문항의 `sourceOracle.catalogCount`와 일치해야 하며 149개·150개 묶음을 구분한다.
150개 묶음은 기존 문항을 유지하고, 복원된 원본을 독립 기준 자료와 대조한 뒤 영향을 받는
검색·비교 정답과 oracle 해시를 새 디렉터리에 동결한다. 기존 149개 묶음과 평가 기록은 보존한다.
현재 로컬 모델의 웹 40문항 기준 결과는 [별도 기록](../verification/2026-11-13-v2-local-llm-baseline-40.md)에 있다.

**앱 환경.** [로컬 개발 환경](../development.md)을 따라 별도 DB·storage의 평가용
backend와 frontend를 시작한다. 동결 자료와 같은 Run 버전을 복원한 DB와 대응 storage가
필요하다. 새로 import해 버전 UUID가 달라진 DB는 같은 기준 데이터로 취급하지 않는다.
평가용 DB에는 QUEUED/RUNNING/NEEDS_INPUT 요청이 없어야 하며, 다른 worker는 실행하지 않는다.
이 명령이 자체 worker를 시작하고 종료한다. 실제 사용자·팀 공용 앱에 연결하지 않는다.
평가 중 문항마다 새 대화를 만들고 선택 태그·기준을 설정하므로 평가 전용 앱을 사용한다.

backend는 `AGENT_MODEL_TIMEOUT_SECONDS=90`과 비밀 `AGENT_WORKER_TOKEN`을 설정한다. `v2_localLLM`의 Qwen 계획·재계획 예약은 호출당 120초이며, 나머지 역할에 공통 제한을 적용한다.
frontend의 `VITE_API_TARGET`도 해당 backend를 가리키게 한다.
연결 파일은 Git 밖에 저장하고 다음 형태로 구성한다. `container`는 이 backend가
사용하는 Docker PostgreSQL의 이름이며, DB 이름·사용자는 `kplasma`다.

```json
{
  "api": "http://127.0.0.1:8089",
  "web": "http://127.0.0.1:5179",
  "container": "your-dedicated-eval-postgres",
  "workerToken": "<same-private-token-as-backend>"
}
```

**먼저 비용 없는 사전 검사.** 저장소 루트에서 실행한다.
이 명령은 입력 자료와 80개 실행 목록만 검사·저장한다. 서버·worker·브라우저·모델에
접속하지 않으므로, 앱 연결과 모델 자격 증명이 맞는지는 유료 실행의 시작 전 검사에서 확인한다.

```sh
npm run eval:agent:local -- --bundle /path/to/private-bundle --output /tmp/agent-plan-001
```

**그다음 유료 실행.** 사전 검사와 다른 새 출력 폴더를 지정한다.

```sh
npm run eval:agent:local -- --live --bundle /path/to/private-bundle --connection /path/to/connection.json --env-file /path/to/eval.env --output /tmp/agent-run-001
```

기본은 브라우저 창을 표시한다. 화면 없이 실행하려면 같은 명령에 `--headless`를 붙인다.
live 시작 전 로컬 URL, 검토 활성 설정, 모델 키, DB에 남은 미완료 요청, backend의 Run
버전·수치·단위·분석 메타데이터를 검사한다. 불일치하면 새 질문을 접수하지 않는다.
DB export는 접수한 request UUID에 한정한 읽기 전용 쿼리다.
DB 조회 제한은 30초이며 모델 호출 제한 90초와 구분한다. 실험 중에는 코드·문항·정답을 수정하지 않는다.

새 출력 폴더만 허용하며 기존 결과를 덮어쓰거나 중단된 유료 요청을 자동 재접수하지 않는다.
도중에 중단되면 `accepted.json`과 서버의 해당 request ID를 먼저 확인한다.
새 폴더로 전체 실험을 다시 시작하는 행위도 새 유료 실행이므로 별도로 결정한다.
평가가 시작한 worker와 브라우저는 종료하지만, 사용자가 준비한 backend·frontend·DB는
종료하거나 삭제하지 않는다.

## 3. 자동개선 테스트셋 · API

| 계획 스텝 | 학습용 | 평가용 |
|---|---:|---:|
| 1 | 10 | 5 |
| 2 | 20 | 10 |
| 3 | 35 | 17 |
| 4 | 35 | 18 |
| **합계** | **100** | **50** |

비공개 문항 디렉터리에는 `learning.json`과 `evaluation.json`을 둔다.
각 문항은 질문, 사전 선택 Run과 기준, 준비한 사용자 입력, 기준 계획, 실제 실행 기대값을 포함한다.
동결 Run 목록과 문항 파일의 해시를 확인하고, API에 보낼 질문·시작 문맥·사용자 선택만 실행에 제공한다.
두 세트의 문항 수, 단계 분포, 고유 ID·질문, 기준 계획과 기대 검색 결과를 사전 검사한다.

자동개선 전 지시문으로 학습용 100문항의 첫 기준을 측정한다. 주지표는 스텝별 **`PLAN_INITIAL` 최초 계획 통과 수와 통과율**이다.
단계 ID와 독립 단계의 순서가 달라도 요청 모드, 조건과 연산자, 값의 출처, 비교·확인 대상이 맞으면 통과한다.
후보 전체를 비교할 때 임의의 정확한 개수 제한을 넣거나, 계산 결과 대신 고정 수치를 넣으면 실패로 기록한다.
최종 실행 자동 검사, Decisions 지적, 재계획 후 복구, 답변 내용 검토 필요 여부는 각자의 지표로 기록한다.

후보 지시문은 학습용에서 기준 대비 개선과 단일 단계의 회귀 여부를 확인한 뒤 평가용에서 비교한다.
학습용 진입 수치는 기준 성적을 확인한 뒤 확정한다. 평가용에서는 기준 지시문과 선택한 수정 지시문을 같은 50문항으로 평가한다.
첫 기준 측정에는 학습용 API 요청 100건만 접수한다.

```sh
npm run eval:agent:local -- --suite automatic-improvement --mode api --split learning \
  --bundle /path/to/frozen-runs --dataset /path/to/automatic-improvement \
  --output /tmp/automatic-improvement-learning-preflight

npm run eval:agent:local -- --suite automatic-improvement --mode api --split learning --live \
  --bundle /path/to/frozen-runs --dataset /path/to/automatic-improvement \
  --connection /path/to/connection.json --env-file /path/to/eval.env \
  --output /tmp/automatic-improvement-luna-low-baseline
```

API 전용 연결 파일에는 `api`, `container`, `workerToken`이 필요하다. 전용 backend와 PostgreSQL을 준비한다.
live 명령은 `gpt-6-luna` low 계획·답변, Luna Decisions, 모델 설정과 그래프 상태의 검토 활성화를 확인한다.
`manifest.json`은 지시문·데이터·소스의 해시를, `summary.json`은 스텝별 최초 계획·실행·복구 집계를 보관한다.
`trials/<문항>-1/execution-records.json`에는 최초 계획 제출, 모든 재계획, Decisions, 계획 revision, 입력·실행 기록이 남는다.
원시 문항·Run 데이터·계획 로그는 비공개 평가 경로에 보관한다.

### 수정용 LLM과 지시문 사본

다음 명령은 `agent/python`에서 실행한다. `BASELINE`은 완료된 일반 V2 학습 기준 평가, `DATASET`은 비공개 문항 디렉터리다. `PROPOSAL`은 새 비공개 디렉터리, `ARMS`는 전용 평가 로그의 상위 디렉터리다. 평가 로그는 평가 체크아웃 및 입력 데이터 디렉터리 밖에 둔다.

```sh
uv run --frozen python -m evals.run_plan_proposal \
  --baseline "$BASELINE" --dataset "$DATASET" --output "$PROPOSAL"
```

기본 명령은 모델 호출 없이 수정용 입력과 감사 기록을 만든다. 실제 제안을 생성할 때는 **다른 새 출력 디렉터리**를 지정하고 같은 명령에 `--generate --env-file "$EVAL_ENV"`를 추가한다. 기본 편집 모델은 `gpt-6-luna` low이며 `--model`, `--effort`로 선택할 수 있다. 이 작업은 수정용 모델을 최대 한 번 호출한다.

| 입력 | 내용 |
|---|---|
| `sections` | 현재 계획 지시문 전체를 제목과 본문으로 나눈 사전. 제목이 문단 ID다. |
| `failures` | 질문, 상대 참조로 표현한 선택·기준 Run, 정답 계획, 기록된 첫 계획, 재채점 차이, 인접 성공 문항 ID. |
| `successes` | 정답 계획의 도구 구성·필드·시작 문맥이 유사한 성공 사례. 각 실패에서 한 건씩 고르고 중복 ID를 합친다. |
| `editor-instructions.txt` | 원인 가설과 근거를 적고 일반화 가능한 기존 문구를 교체하거나 수정을 보류하도록 하는 편집 지침. |

입력 생성기는 기준 지시문·학습 문항 해시, 100문항의 ID와 시도 번호, 요청 ID, 첫 계획 모델 기록, 계획 검토 활성화를 확인한다. 전체 로그에서 첫 계획만 추출한다. 결과가 잘린 시도는 감사 기록에 남긴다. 원시 도구 결과나 평가용 문항은 편집 모델 입력에 넣지 않는다. `audit.json`에는 기준 성적과 같은 로그를 현재 채점기로 재채점한 성적을 각각 기록한다.

모델은 `action`, `section`, `before`, `after`, `reason`, `failure_ids`, `success_ids`를 반환한다. `replace`이면 백엔드가 증거 ID와 문단 내 원문 일치 여부를 검사하고, 유일하게 일치하는 연속된 줄을 교체한다. `candidate.txt`는 전체 후보 지시문, `candidate.diff`는 변경점이다. `no_change`면 근거만 보존한다. 결과가 유효할 때 마지막에 `result.json`이 작성된다. 중단된 디렉터리는 유지하며 같은 디렉터리에 재호출하지 않는다.

### 단계별 검증과 Draft PR

검증기는 동일 채점기로 원본과 수정본의 첫 계획을 문항별로 다시 비교한다. 학습용을 통과하면 별도 평가용에서 두 버전을 비교한다. 통과 기준은 **최초 통과 건수의 순증**과 **기존 1스텝 성공 문항의 회귀 0건**이다. 각각의 순증 하한은 실험자가 명령에 지정한다.

```sh
uv run --frozen python -m evals.validate_plan_proposal \
  --baseline "$BASELINE" --dataset "$DATASET" --proposal "$PROPOSAL" --output "$ARMS" \
  --min-learning-gain "$LEARNING_GAIN" --min-evaluation-gain "$EVALUATION_GAIN"
```

전체 흐름을 한 번에 실행하려면 위 명령에 `--generate-if-missing --evaluate --publish`와 아래 전용 평가 연결 인자를 함께 준다. 새 경로에서는 수정안을 한 번 생성하고, 유효한 기존 제안이 있으면 재사용한다. 모델이 `no_change`를 반환하면 평가와 PR 생성 전에 종료한다.

기본은 이미 완료된 로그의 비교다. `--evaluate --bundle "$BUNDLE" --connection "$CONNECTION" --env-file "$EVAL_ENV"`를 추가하면 빠진 평가를 실행한다. 후보 학습 100건, 학습 기준 충족 시 평가 원본·후보 각 50건으로 최대 200건이다. 완료된 결과는 재사용한다. 불완전한 디렉터리가 있으면 해당 실행을 자동으로 다시 접수하지 않는다. 전용 후보 워커가 사본의 해시를 확인하고 최초 계획과 재계획에서 같은 지시문을 사용한다. 결과는 분할별 기존·후보 통과 건수와 실패→통과·통과→실패 문항 ID를 JSON으로 출력한다.

`--publish`는 두 분할의 기준을 충족한 경우에만 GitHub에 Draft PR을 제출한다. `GH_TOKEN` 또는 `GITHUB_TOKEN`에는 대상 저장소의 Contents 및 Pull requests 쓰기 권한이 필요하다. 기본 대상은 프로젝트 저장소의 `main`이며 `--repo`와 `--base`로 지정할 수 있다.

게시 코드는 GitHub REST API로 원격 기준 소스의 해시를 검사하고 `PLAN_INSTRUCTIONS` 문자열만 바뀌는지 Python 구문 트리로 확인한다. 변경한 파일 하나로 Git tree·commit·작업 브랜치를 만든 다음 `POST /repos/{owner}/{repo}/pulls`를 호출한다. PR 본문에는 합계만 포함한다. 동일 기준 커밋·동일 후보의 재시도는 기존 PR을 찾는다. 팀이 변경을 승인·병합하고 해당 버전을 배포하면 운영 워커가 새 지시문을 사용한다.

## Phoenix와 실패 토큰 관측

실제 평가에서도 `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_API_KEY`, `PHOENIX_PROJECT_NAME` 설정을 worker에 전달한다. Phoenix 사용 시 사전에 모델을 호출하지 않는 연결 trace로 수신을 확인한다. Decisions 단독 실행도 동일한 tracing 초기화·종료를 사용한다.

Responses의 성공·실패·출력 한도 종료 모두 상태, 설정한 `maxOutputTokens`, 제공자가 반환한 입력·출력·추론 토큰과 raw usage를 기록한다. 출력 한도로 잘린 원문과 응답 상태는 오류를 발생시키기 전에 Phoenix에 남기고, 실패한 모델 시도에도 usage와 정제된 response를 저장한다. 로컬 `execution-records.json`에서 같은 내용을 확인할 수 있다. 스트림 종료 응답을 받지 못하면 확보한 텍스트까지만 남기고 usage는 미확인으로 둔다. 타임아웃·연결 실패에서 제공자가 토큰을 반환하지 않았으면 0으로 간주하지 않는다. HTTP 인증 정보와 임의의 provider 오류 메시지, API 키와 판단 메모는 전송하지 않는다.

Phoenix는 실행·복구의 정답이나 상태 저장소로 쓰지 않는다. 토큰량은 제공자 값과 상한을 구분하며, 출력 토큰에는 추론 토큰이 포함될 수 있으므로 본문 길이만으로 한도 초과를 단정하지 않는다. 설정한 상한은 늘리지 않고 역할별 실제 값을 보고한다.

출력 한도 초과 후 복구도 동일 질문 내부의 재계획이며 별도 평가 1회로 세지 않는다. 재계획 입력의 `generation_failure`는 종료 원인·usage·공백 길이·잘린 인수의 짧은 끝부분을 포함한다. 전체 원문은 로컬 모델 시도와 Phoenix에서 확인한다. 코드 오류 후 `rejected_plan`·`validation_error`, 작성 오류 후 `rejected_draft`가 전달됐는지도 호출 기록으로 확인한다. 전 회차와 비교할 때 문항·정답·데이터 버전을 유지하고, 자동 점수와 독립 답변 검토 결과를 분리한다.

## 산출물과 점수 읽기

- `manifest.json`: 입력 해시, 실제 worker 소스 해시, 모델·검토·timeout과 실행량.
- `matrix.json`: 웹 40 / API 40의 예정 목록.
- `results.jsonl`, `summary.json`: 웹/API별 자동 정답 검사와 잠정 재계획 집계.
- `trials/<문항>-<반복>/accepted.json`: 접수 직후 ID. 재실행 전에 확인한다.
- 각 trial의 `result.json`, `execution-records.json`: 최종 응답, 도구·HITL·계획·모델 호출 기록.
- 웹 trial의 화면 캡처·DOM·ARIA·trace: 390/800/1008/1440px와 새로고침 복원 증거.

`summary.json`의 `gradingStage=deterministic_only`는 자동 검사 단계라는 뜻이다.
`answerReviewRequired`가 표시된 설명·혼합 답변은 근거·해석·단위 한계를 독립 검토한 뒤
최종 내용 통과 여부를 확정한다. 내부 Decisions PASS를 정답으로 복사하지 않는다.
명령의 정상 종료도 최종 답변 품질이 전부 통과했다는 뜻이 아니다.

계획 재계획 없음, Decisions 지적 후 재계획, 코드·실행 오류 후 재계획을 구분한다.
`provisionalRecovery`는 자동 정답 기준 잠정 분류이며 최종 답변 검토가 실패하면
복구 성공으로 확정하지 않는다. 답변 재작성은 별도 축이고, 계획 재계획이 없더라도
답변 재작성이 있었으면 모든 단계를 첫 시도에 통과했다고 보고하지 않는다.

화면 자동 검사의 `browserAutomatedUiPass`는 답변 정확도와 별도다.
틀린 답변이나 실패 안내도 정상적으로 표시될 수 있다. 가로 넘침·수식·표·차트의
자동 규칙 외에 모바일 가독성과 실제 차트 내용은 캡처와 원본 근거를 직접 확인한다.
API 전용 결과의 실제 화면까지 추가 검증한 것으로 표시하지 않는다.

기존 `npm run test:e2e:live`는 인공 Run의 소규모 웹 연결 검사이고,
`python -m evals.run_v2 --live`는 인공 Run을 사용하는 160회 메모리 그래프 모델 비교다.
두 명령을 위 웹/API 80문항 평가와 같은 실험으로 집계하지 않는다.

CI는 평가기·HITL·복구 분류를 인공 응답으로 검사하며 두 유료 명령을 자동 실행하지 않는다.
내부 평가의 집계 성적과 재현 방법은 문서·PR에 기록할 수 있다. 실제 Run 데이터,
사용자 원문을 포함한 평가 파일·trace·스크린샷과 비밀값은 GitHub Actions·PR artifact에 올리지 않는다.


## 웹 일부 문항 실행

`evals.run_flow`는 전체 40문항 은행을 검증한 뒤 `--mode browser --limit 5`로 첫 5문항만 선택할 수 있다. 기본값은 기존 40 browser + 40 API다. manifest·진행·완료 검사는 선택한 행렬의 실제 개수를 사용하며 실패 문항을 자동 재접수하지 않는다.

이번 llama.cpp 구성 비교는 Q01~Q05 각 1회, API 모드 접수 0회로 제한한다. 기존 같은 다섯 문항의 자동 통과는 1/5이며 전체 성적 5/40과 구분한다. [전환·평가 계획](../plans/2026-11-13-001-v2-local-llm-llamacpp-thinking-web5.md)을 따른다.

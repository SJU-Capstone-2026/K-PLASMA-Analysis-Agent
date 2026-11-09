# v2 평가 실행: Decisions와 Agent 전체 흐름

두 평가는 별도 수동 명령이다. Decisions 단독 평가는 고정 계획의 의미 판별을,
Agent 전체 평가는 모델이 직접 계획을 만드는 웹·API 흐름을 검사한다.
두 유료 명령을 CI나 하나의 자동 실행 명령으로 묶지 않는다.

| 평가 | 기본 실행량 | 범위 | 외부 준비물 |
| --- | --- | --- | --- |
| Decisions 단독 | 80회: 정상 40 / 오류 40 | 원문과 고정 계획의 의미 일치 판별 | 모델 키 |
| Agent 전체 흐름 | 80개 질문: 웹 40 / API 40 | 계획 → 검토 → 도구·HITL → 필요한 답변·검토·수정 → 저장 | 모델 키, 비공개 고정 문항·정답 묶음, 격리 DB·backend·frontend |

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
AGENT_V2_ANSWER_MODEL=gpt-5.6-luna
AGENT_V2_ANSWER_REASONING_EFFORT=none
AGENT_V2_DECISIONS_MODEL=gpt-6-luna
AGENT_V2_PLAN_REVIEW_ENABLED=true
AGENT_MODEL_TIMEOUT_SECONDS=90
```

실제 Agent 평가는 계획 의미 검토를 켠다. 설정이 꺼져 있으면 시작을 거부한다.
새 요청의 그래프 상태도 활성 설정으로 초기화되며, 실제 데이터 도구를 실행한 요청에는
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

## 2. Agent 전체 흐름: 웹 40 + API 40

`eval:agent:local`은 같은 40문항을 먼저 실제 브라우저에서 한 번씩,
다음으로 실제 backend API에서 한 번씩 실행한다. 메모리 그래프로 대체하지 않는다.
브라우저는 실제 입력·버튼·선택창을 조작하고, API는 미리 정한 사용자 선택을
실제 `NEEDS_INPUT`·선택지·revision에 맞춰 같은 요청의 resume API로 전달한다.

**입력 데이터.** Git 밖의 비공개 묶음 디렉터리에 다음 파일을 준비한다.
이미 사용한 동결 문항과 독립 정답을 그대로 재사용하며 임의로 최신 데이터에서
정답을 다시 생성하지 않는다. 이 자료는 저장소나 PR artifact에 포함하지 않는다.

| 파일 | 역할 |
| --- | --- |
| `cases.json` | 고정 40문항, 선택 Run·기준, HITL 선택, 기대 필터·정렬·수치·정답 집합과 검토 기준 |
| `runs.json` | 고정 149개 Run의 불변 버전, 조건, 수치, 단위·분석 메타데이터 |
| `wave-expected.json` | 원본 파형에서 독립 계산한 기대값 |
| `distribution-expected.json` | 원본 분포에서 독립 계산한 기대값·부재 이유 |
| `oracle-overrides.json` | 해당 oracle 해시와 일치하는 동결 정답 보정이 있는 경우 함께 공급 |

실행기는 문항별 oracle 해시, 40개 고유 문항과 범주 구성, 기대 검색 결과·계산을
확인한다. 다른 자료나 잘못된 정답 묶음을 사용하면 사전 검사에서 중단한다.
새 문항을 추가하는 실험은 기존 기준을 덮어쓰지 말고 별도 버전으로 준비한다.

**앱 환경.** [로컬 개발 환경](../development.md)을 따라 별도 DB·storage의 평가용
backend와 frontend를 시작한다. 동결 자료와 같은 Run 버전을 복원한 DB와 대응 storage가
필요하다. 새로 import해 버전 UUID가 달라진 DB는 같은 기준 데이터로 취급하지 않는다.
평가용 DB에는 QUEUED/RUNNING/NEEDS_INPUT 요청이 없어야 하며, 다른 worker는 실행하지 않는다.
이 명령이 자체 worker를 시작하고 종료한다. 실제 사용자·팀 공용 앱에 연결하지 않는다.
평가 중 문항마다 새 대화를 만들고 선택 태그·기준을 설정하므로 평가 전용 앱을 사용한다.

backend는 `AGENT_MODEL_TIMEOUT_SECONDS=90`과 비밀 `AGENT_WORKER_TOKEN`을 설정한다.
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

CI는 평가기·HITL·복구 분류를 인공 응답으로 검사한다. 이 두 유료 명령과 비공개
데이터·실험 결과·스크린샷은 GitHub Actions와 PR artifact에 올리지 않는다.

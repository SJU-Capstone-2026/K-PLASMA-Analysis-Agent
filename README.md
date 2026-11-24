# PLASMATE

<img src="frontend/public/plasmate.png" alt="PLASMATE 마스코트" width="160">

세종대학교 컴퓨터공학과 2026-2 캡스톤 프로젝트. 등록된 플라즈마 실험 Run을 조회하고 공정 조건을 비교해 다음 실험의 근거를 찾습니다.

| 기능 | 동작 |
| --- | --- |
| **분석 Agent · 일반** | 표준 V2가 질문을 계획하고 OpenAI 모델로 검토합니다. 조건 조회, 목표 후보 탐색, Run 비교, 변화·개념 설명을 지원합니다. |
| **분석 Agent · 로컬** | LocalLLM v2.8의 Qwen이 계획을 작성하고, 코드가 원문에서 확정 가능한 조건과 단계 연결을 보완한 뒤 Flash가 검토합니다. 모델 요청은 기기 안에서 처리합니다. |
| **의사결정 Agent** | 목표를 지표로 풀어 사용자에게 확인받고, 표준 V2로 다음 실험 후보의 수치와 장단점을 비교합니다. |
| **Run 관리** | 폴더·ZIP으로 등록한 실험의 원본과 불변 버전을 보존하고 상세 수치와 그래프를 표시합니다. |

분석 Agent의 **Agent 버전**에서 일반 V2나 로컬 V2를 선택합니다. 실행 모드를 바꾸려면 새 대화를 열고 원하는 버전을 고릅니다. 이전 대화는 왼쪽 목록에서 다시 볼 수 있습니다.

## 실행하기

Java 21, Node 22.23.3, npm 10.9.9, uv, Docker를 준비합니다. 아래 명령은 저장소 루트에서 실행합니다.

### 처음 한 번

```sh
npm ci
uv sync --project agent/python --frozen
test -f .env || cp .env.example .env
```

`.env`에 로컬 DB 비밀번호를 설정합니다. 일반 V2를 쓰려면 `OPENAI_API_KEY`와 백엔드·워커가 공유할 `AGENT_WORKER_TOKEN`도 설정합니다. [환경 설정 안내](docs/development.md#팀-로컬-실행)

### 서버 실행

Docker를 켠 뒤 아래 명령을 각 터미널에서 실행합니다. 백엔드가 준비되면 프런트엔드와 사용할 워커를 시작합니다.

**터미널 1 · PostgreSQL과 백엔드**

```sh
set -a
source .env
set +a
docker compose up -d --wait postgres
backend/gradlew -p backend bootRun
```

**터미널 2 · 프런트엔드**

```sh
set -a
source .env
set +a
npm run dev
```

**터미널 3 · 일반 V2 워커**

```sh
npm run dev:agent
```

[분석 화면](http://127.0.0.1:5173)을 엽니다. 백엔드 상태는 [헬스 체크](http://127.0.0.1:8080/api/health)에서 확인할 수 있습니다.

### 로컬 V2도 사용하기

일반·로컬은 PostgreSQL, 백엔드, 프런트엔드를 공유합니다. Apple Silicon에서 Qwen·Flash와 메모리 검사를 준비한 뒤, `.env.local-llm.example` 하단의 공용 서버 설정을 `.env`에 적용합니다. 백엔드의 `AGENT_LOCAL_WORKER_TOKEN`을 `.env.local-llm`의 `AGENT_V2_LOCAL_LLM_WORKER_TOKEN`과 맞추고, 일반 워커에는 별도 키를 사용합니다. [모델 준비와 공용 서버 설정](docs/development/agent-v2-local-llm.md#공통-backend와-화면)

로컬 분석을 쓸 때는 별도 터미널에서 아래 워커를 시작합니다. 두 모드를 함께 쓰려면 두 워커를 모두 켭니다.

```sh
npm run dev:agent:local -- --env-file .env.local-llm
```

로컬 모드도 같은 화면 주소로 바로 접속합니다. 브라우저 연결 파일이나 세션 키를 준비할 필요가 없습니다.

의사결정 Agent만 둘러보려면 의존성 설치 후 `npm run dev:decision-demo`로 인공 Run과 고정 모델 응답을 쓰는 시연을 실행할 수 있습니다. [의사결정 시연 안내](docs/development/conversation-rooms.md)

| 경로 | 역할 |
| --- | --- |
| `frontend/` | React·TypeScript 화면 |
| `backend/` | Spring Boot API, PostgreSQL 저장, Run 업로드·파싱 |
| `agent/python/` | LangGraph 일반 V2와 LocalLLM 워커 |

## 개발과 검증

- [표준 V2 그래프와 평가](docs/development/agent-v2.md)
- [공용 API 계약](docs/api/openapi.yaml)
- [프로토타입 수용 검증](docs/verification/acceptance.md)
- [협업 가이드](CONTRIBUTING.md) · [저장소 작업 규칙](AGENTS.md) · [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)

PR CI는 인공 데이터와 고정 모델 응답으로 두 실행 모드의 계약, 브라우저, 재시작 복구를 검사합니다. 실제 모델 평가와 별도 검증 명령은 [팀 실행 가이드의 검증 절차](docs/development.md#검증)를 따릅니다.

## 실제 기업 데이터 관리

실제 기업 실험 데이터인 **기준 150개 Run의 원본·측정 수치·그래프는 보안상 GitHub 저장소에 포함하지 않았습니다.** 원본은 로컬 `backend/storage/`에, 등록된 수치와 그래프는 로컬 PostgreSQL에 보관합니다. [`.gitignore`](.gitignore)에 실제 결과 폴더, `analysis-data.js`, 백업·로그 보관 경로, 비공개 환경 설정을 명시해 Git 추적에서 제외합니다.

같은 150개 Run이 필요한 팀원은 승인된 별도 경로로 원본을 받아 각자 등록합니다. [실제 Run 등록 방법](docs/development.md#실제-150-run-초기-적재와-재처리)

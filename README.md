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

Java 21, Node 22.23.3, npm 10.9.9, uv, Docker를 준비합니다. Python은 `agent/python/.python-version`과 잠금 파일을 따릅니다.

- [팀 로컬 실행 가이드](docs/development.md)에서 PostgreSQL, Spring Boot, Vite, 일반 V2 워커를 시작합니다.
- [LocalLLM 준비 가이드](docs/development/agent-v2-local-llm.md)에서 Apple Silicon용 Qwen·Flash, 로컬 연결 인증, 메모리 검사를 준비합니다. 일반·로컬은 웹, 백엔드, DB를 공유하고 각각의 워커가 질문을 처리합니다.
- 의사결정 Agent를 먼저 보려면 공통 의존성을 설치한 뒤 `npm run dev:decision-demo`를 실행합니다. 미리보기는 인공 Run과 고정 모델 응답을 사용합니다. [의사결정 시연 안내](docs/development/conversation-rooms.md)

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

실제 Run 원본·그래프, DB 백업, 사용자 대화, 비밀값과 원시 평가 로그는 Git에서 제외한 경로에 보관합니다. 기준 150 Run은 GitHub 밖에서 공유하고 각자 등록합니다.

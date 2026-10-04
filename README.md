# K-PLASMA-Analysis-Agent
세종대학교 2026-2 캡스톤 컴싸 레파지토리

## 프로젝트 방향

K-PLASMA 프로토타입 v12.3.1의 UI·UX와 기능을 실제 애플리케이션으로 이관합니다. 신규 질문은 Python LangGraph v1에서 처리합니다. 순방향 조회·역방향 탐색·Run 비교·변화 설명·개념 설명을 지원하며, 실제 파일 업로드·파싱·재처리를 제공합니다. 1차 사용 환경은 팀원 각자의 로컬 개발 환경입니다.

주요 제품 코드 영역은 `backend/`, `frontend/`, `agent/`로 구성합니다.

- 백엔드: Spring Boot + Gradle
- 프론트엔드: React + TypeScript + Vite
- 데이터베이스: PostgreSQL

`frontend`는 화면, `backend`는 데이터와 요청·결과의 영속 저장, `agent/python`은 LangGraph v1 worker를 담당합니다. 기존 JavaScript fallback 소스·테스트·과거 답변 렌더러는 보존하지만 신규 질문 경로에서는 호출하지 않습니다. 모델 연결 오류는 명시적으로 표시합니다.

## 설계와 계획

- [Agent Graph v1 구현 계획](docs/superpowers/plans/2026-10-04-agent-graph-v1-plan.md): 다섯 도구·질문 해석·수치 검증·장애 복구 계약.
- [Agent v1 구현·검증 기록](docs/verification/agent-v1.md): 실제 모델·프로세스 장애·원본 scalar 대조 결과와 남은 검토 범위.
- [v12.3.1 실제 구현 설계](docs/superpowers/specs/2026-10-03-v12.3.1-implementation-design.md): 사용자 승인된 기능·데이터 정책과 검증 기준. 데이터 범위는 기존 3변수의 150 Run입니다.
- [상세 구현 계획](docs/superpowers/plans/2026-10-03-v12.3.1-implementation-plan.md): 12개 구현 작업, 공통 계약, 의존 순서·PR 단위·검증 기준. 사용자가 승인했으며 작업별 구현·검토 방식으로 진행합니다.
- [기준 프로토타입 조사](docs/superpowers/research/2026-10-03-v12.3.1-discovery.md): 화면·fallback·수치·원본 파일과 기존 테스트 확인 결과.

승인된 12개 작업의 제품 구현과 로컬 검증을 마쳤으며 최종 리뷰의 Catalog 진행 재개·상세 disclosure·Turn UUID 수정도 반영했습니다. 검증 범위와 유예는 [수용 검증](docs/verification/acceptance.md)에 기록했습니다. 최종 수정의 독립 리뷰와 PR 전달은 별도 gate이며 원격 CI나 팀원의 clean-clone 실행 완료를 의미하지 않습니다.

## 로컬 실행과 검증

Java 21, Node 22.23.3, npm 10.9.9, uv와 Docker를 준비한 뒤 [팀 실행 문서](docs/development.md)를 따라 PostgreSQL·backend·Python worker·frontend를 시작합니다. Python은 `agent/python/.python-version`과 `uv.lock`으로 고정합니다. `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-5.6-luna`, `OPENAI_REASONING_EFFORT=none`, backend·worker 공통 `AGENT_WORKER_TOKEN`을 설정합니다.

```sh
npm ci
uv sync --project agent/python --frozen
npm test
npm run test:agent
npm run typecheck
npm run lint
npm run build
backend/gradlew -p backend test --console=plain
npm exec --workspace frontend -- playwright install chromium
npm run test:e2e
npm run verify:public-files
```

`test:e2e`는 독립 PostgreSQL·backend·Python 그래프와 고정 모델 응답을 사용하는 인공 데이터 검증입니다. `test:e2e:live`는 실제 LLM을 연결합니다. 이전 fallback의 원본 비교 실행기는 보존했으며 현재 v1 통과 기준과의 차이는 [실행 문서](docs/development.md)에 설명합니다. 기본 CI는 실제 데이터나 API 키를 포함하지 않으며 검증 artifact를 업로드하지 않습니다.

[수용 검증](docs/verification/acceptance.md)과 [원본 102개 대응표](docs/verification/prototype-test-map.md)는 통과·실패·유예·미검증 범위를 구분합니다. D1–D5와 남은 차이가 있으므로 전체 100% 동등성으로 표현하지 않습니다. 새 대화와 데모 초기화는 업로드한 Run·그래프·원본을 유지합니다. 종료 절차는 DB volume과 원본을 보존합니다.

## 코드와 실제 데이터의 공유

GitHub에는 코드·설계 문서·DB 스키마·마이그레이션·설정 예시를 관리합니다. 실제 결과 원본, 실제 결과·그래프 JSON, DB 데이터·백업, 사용자 대화·판단 기록은 올리지 않습니다. 해당 로컬 보관 경로는 `.gitignore`에서 제외합니다.

1차에는 팀원 각자가 코드를 clone하고 자기 데이터를 업로드해 개발합니다. 같은 기준 150개 Run이 필요한 경우 데이터는 GitHub 밖에서 공유해 각자 적재합니다. clone만으로 실제 데이터가 제공되는 구성은 아닙니다. 데이터 적재·검증 절차는 구현 계획에 포함합니다.

팀 공용 백엔드·DB·파일 보관소는 후속 작업입니다.

## 협업 문서

- [협업 가이드](CONTRIBUTING.md): 작업 브랜치, PR, 리뷰, 검증 및 원격 저장소 보호 설정
- [저장소 작업 규칙](AGENTS.md): 개발자와 코딩 에이전트가 함께 지킬 규칙
- [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)

모든 변경은 작업 브랜치에서 진행하고 PR로 반영합니다. `main` 직접 push는 금지합니다. 브랜치 보호와 CI는 원격 저장소 연결 후 별도로 설정해야 합니다.

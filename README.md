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
npm run test:ui:v2
npm run test:e2e
npm run test:agent:restart
npm run verify:public-files
```

기본 CI의 Agent 실행·평가·브라우저 기준은 v2입니다. `test:agent`는 v2 그래프·평가기와 공통 계산을, `test:ui:v2`는 네 화면 폭의 그래프·대화방·스트리밍을 검사합니다. `test:e2e`와 `test:agent:restart`는 독립 PostgreSQL·backend·Python v2 그래프에서 고정 모델 응답을 사용합니다. `test:e2e:live`는 실제 LLM을 연결하므로 API 키와 호출 비용이 필요합니다. 공통 API·보안·과거 기록 호환성 검사는 유지합니다. 기본 CI는 실제 데이터나 API 키를 포함하지 않으며 검증 artifact를 업로드하지 않습니다. 자세한 범위와 실제 모델 평가 명령은 [Agent v2 운영과 평가](docs/development/agent-v2.md)를 참고하세요.

[수용 검증](docs/verification/acceptance.md)과 [원본 102개 대응표](docs/verification/prototype-test-map.md)는 통과·실패·유예·미검증 범위를 구분합니다. D1–D5와 남은 차이가 있으므로 전체 100% 동등성으로 표현하지 않습니다. 새 대화와 데모 초기화는 업로드한 Run·그래프·원본을 유지합니다. 종료 절차는 DB volume과 원본을 보존합니다.

## 독립 V3와 판단 기록 RAG

V3는 V2를 보존한 별도 구현이다. 새 대화의 **Agent 버전 → v3**에서 **판단 기록 규칙**과 **RAG**를 각각 선택한다. 선택한 기능은 요청 시작 때 저장되며 진행 중 선택·재계획·재시작에도 유지된다. 신규 V3 실행은 `cost-regex-2`로 비용 반려 전체 이력을 집계하며, 과거 `cost-regex-1` 저장 결과는 기존 정책으로 읽는다. 필수 수치 검증과 계획 Decisions는 두 스위치와 별개로 유지한다.

V3 검색 의존성은 `agent/python/requirements-v3-rag.lock`에 버전과 해시를 고정했다. 아래 설치 명령은 **V3 전용 clone**에서 실행한다. 기존 V1/V2 작업 폴더의 환경을 덮어쓰지 않는다. 기존 `.env`를 예시로 덮어쓰지 말고 `.env.example`의 `AGENT_V3_` 설정을 자기 환경에 추가한다.

```sh
uv venv agent/python/.venv --python 3.12.15
uv pip sync --python agent/python/.venv/bin/python --require-hashes agent/python/requirements-v3-rag.lock
```

Windows의 Python 실행 파일은 `agent/python/.venv/Scripts/python.exe`다. `npm run dev:agent`는 저장소의 Python 소스를 경로에 추가하고 해당 환경을 사용한다. 모델 파일은 자기 로컬 폴더에 준비하고 `AGENT_V3_RAG_MODEL_DIR`, 인덱스는 `AGENT_V3_RAG_CACHE_DIR`로 지정한다. 공개 모델 파일만 내려받는 준비 명령은 다음과 같으며 프로젝트 기록을 전송하지 않는다.

```sh
PYTHONPATH=agent/python/src agent/python/.venv/bin/python -c "from pathlib import Path; from kplasma_agent.v3.decision_rag.embedding import download; download(Path('.local/models/multilingual-e5-small'))"
```

V3에서 판단 이력을 조회할 때는 등록된 `RUN-…` 이름을 질문에 그대로 쓰거나 Run을 명시적으로 첨부한다. 서버는 이름을 등록 ID와 정확히 대조하여 버전을 고정하며, 명시적으로 첨부한 과거 버전은 유지한다. 이름이나 버전을 확정하지 못하면 구체적인 확인·첨부 안내를 표시한다. 검색은 해당 Run·버전·귀속 범위와 원문 출처를 보존하며, RAG 유사도로 확정 제외 규칙을 완화하지 않는다. 모의 기록을 사용하는 환경만 `AGENT_V3_RAG_SYNTHETIC=true`로 표시한다. clone이나 모델 준비가 실제 Run·판단 기록을 생성하지는 않는다.

[V3 판단 기록 RAG 구현과 실행 방법](docs/development/agent-v3-decision-rag.md)에서 그래프 연결, 요청별 스위치, 이름 입력과 근거 저장 계약을 설명한다. 성능 평가 결과·회차별 원인 분석은 구현과 분리해 제출하며, 웹/API의 유료 비교는 CI에서 실행하지 않는다.

## 코드와 실제 데이터의 공유

GitHub에는 코드·설계 문서·DB 스키마·마이그레이션·설정 예시를 관리합니다. 실제 결과 원본, 실제 결과·그래프 JSON, DB 데이터·백업, 사용자 대화·판단 기록은 올리지 않습니다. 해당 로컬 보관 경로는 `.gitignore`에서 제외합니다.

1차에는 팀원 각자가 코드를 clone하고 자기 데이터를 업로드해 개발합니다. 같은 기준 150개 Run이 필요한 경우 데이터는 GitHub 밖에서 공유해 각자 적재합니다. clone만으로 실제 데이터가 제공되는 구성은 아닙니다. 데이터 적재·검증 절차는 구현 계획에 포함합니다.

팀 공용 백엔드·DB·파일 보관소는 후속 작업입니다.

## 협업 문서

- [협업 가이드](CONTRIBUTING.md): 작업 브랜치, PR, 리뷰, 검증 및 원격 저장소 보호 설정
- [저장소 작업 규칙](AGENTS.md): 개발자와 코딩 에이전트가 함께 지킬 규칙
- [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)

모든 변경은 작업 브랜치에서 진행하고 PR로 반영합니다. `main` 직접 push는 금지합니다. 브랜치 보호와 CI는 원격 저장소 연결 후 별도로 설정해야 합니다.

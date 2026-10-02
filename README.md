# K-PLASMA-Analysis-Agent
세종대학교 2026-2 캡스톤 컴싸 레파지토리

## 프로젝트 방향

K-PLASMA 프로토타입 v12.3.1의 UI·UX와 기능을 실제 애플리케이션으로 이관합니다. 초기에는 기존 결정론적 fallback을 사용하며 실제 파일 업로드·파싱·재처리를 구현합니다. 1차 사용 환경은 팀원 각자의 로컬 개발 환경입니다.

주요 제품 코드 영역은 `backend/`, `frontend/`, `agent/`로 구성할 예정입니다.

- 백엔드: Spring Boot + Gradle
- 프론트엔드: React + TypeScript + Vite
- 데이터베이스: PostgreSQL

`frontend`는 화면, `backend`는 업로드·파싱·원본 보관·DB, `agent`는 기존 JavaScript fallback 라이브러리를 담당합니다. 초기에는 Agent를 별도 서버로 실행하지 않습니다.

## 설계와 계획

- [v12.3.1 실제 구현 설계](docs/superpowers/specs/2026-10-03-v12.3.1-implementation-design.md): 합의한 기능·데이터 정책과 검증 기준. 현재 작성된 문서의 사용자 검토를 기다리고 있습니다.
- [기준 프로토타입 조사](docs/superpowers/research/2026-10-03-v12.3.1-discovery.md): 화면·fallback·수치·원본 파일과 기존 테스트 확인 결과.

상세 구현 계획서는 설계 문서 검토 후 작성합니다. 제품 코드는 아직 생성하지 않았습니다.

## 코드와 실제 데이터의 공유

GitHub에는 코드·설계 문서·DB 스키마·마이그레이션·설정 예시를 관리합니다. 실제 결과 원본, 실제 결과·그래프 JSON, DB 데이터·백업, 사용자 대화·판단 기록은 올리지 않습니다. 해당 로컬 보관 경로는 `.gitignore`에서 제외합니다.

1차에는 팀원 각자가 코드를 clone하고 자기 데이터를 업로드해 개발합니다. 같은 기준 150개 Run이 필요한 경우 데이터는 GitHub 밖에서 공유해 각자 적재합니다. clone만으로 실제 데이터가 제공되는 구성은 아닙니다. 데이터 적재·검증 절차는 구현 계획에 포함합니다.

팀 공용 백엔드·DB·파일 보관소는 후속 작업입니다.

## 협업 문서

- [협업 가이드](CONTRIBUTING.md): 작업 브랜치, PR, 리뷰, 검증 및 원격 저장소 보호 설정
- [저장소 작업 규칙](AGENTS.md): 개발자와 코딩 에이전트가 함께 지킬 규칙
- [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)

모든 변경은 작업 브랜치에서 진행하고 PR로 반영합니다. `main` 직접 push는 금지합니다. 브랜치 보호와 CI는 원격 저장소 연결 후 별도로 설정해야 합니다.

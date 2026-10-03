# K-PLASMA-Analysis-Agent
세종대학교 2026-2 캡스톤 컴싸 레파지토리

## 프로젝트 방향

K-PLASMA 프로토타입 v12.3.1의 UI·UX와 기능을 실제 애플리케이션으로 이관합니다. 초기에는 기존 결정론적 fallback을 사용하며 실제 파일 업로드·파싱·재처리를 구현합니다. 1차 사용 환경은 팀원 각자의 로컬 개발 환경입니다.

주요 제품 코드 영역은 `backend/`, `frontend/`, `agent/`로 구성합니다.

- 백엔드: Spring Boot + Gradle
- 프론트엔드: React + TypeScript + Vite
- 데이터베이스: PostgreSQL

`frontend`는 화면, `backend`는 업로드·파싱·원본 보관·DB, `agent`는 기존 JavaScript fallback 라이브러리를 담당합니다. 초기에는 Agent를 별도 서버로 실행하지 않습니다.

## 설계와 계획

- [v12.3.1 실제 구현 설계](docs/superpowers/specs/2026-10-03-v12.3.1-implementation-design.md): 사용자 승인된 기능·데이터 정책과 검증 기준. 데이터 범위는 기존 3변수의 150 Run입니다.
- [상세 구현 계획](docs/superpowers/plans/2026-10-03-v12.3.1-implementation-plan.md): 12개 구현 작업, 공통 계약, 의존 순서·PR 단위·검증 기준. 사용자가 승인했으며 작업별 구현·검토 방식으로 진행합니다.
- [기준 프로토타입 조사](docs/superpowers/research/2026-10-03-v12.3.1-discovery.md): 화면·fallback·수치·원본 파일과 기존 테스트 확인 결과.

제품 코드는 승인된 계획 순서대로 구현 중입니다. 완료된 실행 절차와 검증 결과는 각 작업에서 갱신합니다.

## 로컬 실행 (Task 1)

Java 21 (검증: Temurin 21.0.12.1), Node **22.23.3**, npm **10.9.9**, 실행 중인 Docker가 필요합니다. Gradle **8.14.3**은 체크인된 Wrapper가 내려받고 체크섬으로 검증합니다. Spring Boot **4.1.1**, PostgreSQL **18.6-alpine3.24**를 사용하며 npm 의존성의 정확한 버전은 `package-lock.json`에 기록합니다. Node 버전 관리 도구에서 `.node-version`을 적용하고 `JAVA_HOME`을 Java 21 설치 경로로 지정하세요.

저장소 루트에서 설치하고 비공개 로컬 설정을 준비합니다. `.env`의 `POSTGRES_PASSWORD`는 직접 설정하세요. 비밀번호는 Git에 넣지 않습니다.

```sh
npm ci
cp .env.example .env
# .env에서 POSTGRES_PASSWORD를 설정한 다음 실행
set -a
source .env
set +a
docker compose config --quiet
docker compose up -d --wait postgres
```

DB 다음으로 backend를 시작합니다. `bootRun`의 작업 폴더는 `backend/`이므로 기본 `./storage`는 `backend/storage/`입니다. 폴더는 readiness 확인 때 없으면 생성하며 기존 파일은 유지합니다. 다른 작업 폴더에서 JAR를 직접 실행한다면 `KPLASMA_STORAGE_ROOT`에 저장소의 절대 경로를 지정하세요.

```sh
backend/gradlew -p backend bootRun
```

별도 터미널에서 저장소 루트의 frontend를 시작합니다. 기본 포트는 backend **8080**, frontend **5173**, PostgreSQL **5432**입니다. frontend의 `/api` 요청은 `VITE_API_TARGET`으로 프록시됩니다. `.env`에서 DB 포트를 바꾸면 `DB_URL`의 포트도 함께 바꾸세요.

```sh
npm run dev
curl http://localhost:8080/api/health
# 준비됨: {"status":"UP","database":"UP","storage":"UP"}
# DB 질의 또는 실제 보관소 쓰기 실패: HTTP 503, 해당 상태 DOWN
```

이 단계의 frontend는 빈 React 부트 엔트리입니다. 화면과 결정론적 fallback은 후속 작업에서 이관합니다. `agent`는 npm workspace 라이브러리이며 별도 프로세스로 실행하지 않습니다.

종료는 backend와 frontend 터미널에서 각각 `Ctrl+C`, DB는 다음 명령을 사용합니다. 일반 종료는 DB 볼륨과 `backend/storage/` 데이터를 보존합니다.

```sh
docker compose stop postgres
```

검증은 저장소 루트에서 실행합니다. backend 테스트는 Docker에서 격리된 실제 PostgreSQL 18 컨테이너와 임시 보관 폴더를 사용하며 개발 DB에는 접속하지 않습니다. npm workspace 테스트는 이 초기 단계에 테스트 파일이 없는 상태를 허용합니다.

```sh
backend/gradlew -p backend test --tests '*StartupSmokeTest'
backend/gradlew -p backend test
docker compose config --quiet
npm run build
npm run typecheck
npm run lint
npm test
```

버전 선택 근거: [Spring Boot 요구사항](https://docs.spring.io/spring-boot/system-requirements.html), [Node LTS](https://nodejs.org/en/download), [PostgreSQL 공식 이미지](https://hub.docker.com/_/postgres). Java/Node의 이번 로컬 검증용 런타임은 `backend/.runtime/`에만 두며 Git에 포함하지 않습니다.

## 코드와 실제 데이터의 공유

GitHub에는 코드·설계 문서·DB 스키마·마이그레이션·설정 예시를 관리합니다. 실제 결과 원본, 실제 결과·그래프 JSON, DB 데이터·백업, 사용자 대화·판단 기록은 올리지 않습니다. 해당 로컬 보관 경로는 `.gitignore`에서 제외합니다.

1차에는 팀원 각자가 코드를 clone하고 자기 데이터를 업로드해 개발합니다. 같은 기준 150개 Run이 필요한 경우 데이터는 GitHub 밖에서 공유해 각자 적재합니다. clone만으로 실제 데이터가 제공되는 구성은 아닙니다. 데이터 적재·검증 절차는 구현 계획에 포함합니다.

팀 공용 백엔드·DB·파일 보관소는 후속 작업입니다.

## 협업 문서

- [협업 가이드](CONTRIBUTING.md): 작업 브랜치, PR, 리뷰, 검증 및 원격 저장소 보호 설정
- [저장소 작업 규칙](AGENTS.md): 개발자와 코딩 에이전트가 함께 지킬 규칙
- [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)

모든 변경은 작업 브랜치에서 진행하고 PR로 반영합니다. `main` 직접 push는 금지합니다. 브랜치 보호와 CI는 원격 저장소 연결 후 별도로 설정해야 합니다.

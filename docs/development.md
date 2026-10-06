# 팀 로컬 실행

저장소를 clone한 뒤 저장소 루트에서 실행한다. Java 21, Node 22.23.3(`.node-version`), npm 10.9.9, uv, 실행 중인 Docker가 필요하다. Gradle 8.14.3은 Wrapper가 설치한다. PostgreSQL 18.6-alpine3.24는 Compose와 검증 실행기가 사용한다. 실행 프로세스는 PostgreSQL·backend·Python LangGraph worker·frontend 네 개다. Python 패치 버전과 의존성은 `agent/python/.python-version`, `uv.lock`으로 고정한다.

```sh
npm ci
cp .env.example .env
uv sync --project agent/python --frozen
```

자기 `.env`에서 비밀번호를 설정한다. `source .env`는 셸 코드로 읽으므로 공백·`$`·`!`·`#` 등의 문자가 있는 값은 작은따옴표로 감싼다. 예: `POSTGRES_PASSWORD='choose-your-local-password!$#'`. 이 예시를 그대로 공용 비밀번호로 쓰지 않는다. `.env`는 Git에서 제외되며 예시 파일만 공유한다. 작은따옴표 자체가 포함되는 복잡한 값은 셸과 Compose 양쪽에서 안전하게 읽히는지 확인한다. 타인이 보낸 `.env`를 검토 없이 source하지 않는다.

`OPENAI_API_KEY`와 backend·worker가 공유하는 무작위 `AGENT_WORKER_TOKEN`도 설정한다. 모델 기본값은 `gpt-5.6-luna`, 추론 수준은 `none`이다. 키는 브라우저로 보내지 않으며 worker만 읽는다. 토큰 생성 예: `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. 출력은 자신의 `.env`에만 저장한다. 이미 `.env`가 있다면 예시 파일로 덮어쓰지 않는다.

기본 DB 5432가 이미 사용 중이면 `POSTGRES_PORT=15432`처럼 비어 있는 포트를 골라 `DB_URL=jdbc:postgresql://localhost:15432/kplasma`도 함께 바꾼다. backend 기본 8080을 바꾸면 `BACKEND_PORT`와 `VITE_API_TARGET`을 함께 바꾼다. 기존 Docker 컨테이너를 종료할 필요는 없다.

backend는 기본 `SERVER_ADDRESS=127.0.0.1`로 로컬에서만 접속할 수 있다. 공개 API에는 사용자 인증이 없으므로 다른 호스트에 노출하려면 인증 프록시와 접근 제어를 구성한 뒤 `SERVER_ADDRESS`를 명시적으로 바꾼다. 내부 worker 토큰은 공개 API의 사용자 인증을 대신하지 않는다.

```sh
set -a
source .env
set +a
docker compose config --quiet
docker compose up -d --wait postgres
backend/gradlew -p backend bootRun
```

별도 터미널에서도 자신의 `.env`를 같은 방법으로 읽은 뒤 실행한다.

```sh
npm run dev
curl http://localhost:8080/api/health
```

추가 터미널에서 worker를 실행한다. worker는 저장소 `.env`를 dotenv로 읽으므로 셸 source 없이도 시작할 수 있다.

```sh
npm run dev:agent
```

새 질문은 v1 서버 요청으로만 접수된다. 모델이나 worker가 없을 때 JavaScript fallback으로 전환하지 않는다. 대기 중인 요청은 PostgreSQL에 남으며 worker가 다시 시작하면 회수한다. 실행 중인 작업은 임대가 만료된 뒤 재개되므로 강제 종료 후 최대 약 일 분이 필요할 수 있다. 다른 그래프·프롬프트·모델 설정으로 바뀐 미완료 작업은 `RECOVERY_VERSION_MISMATCH`로 종료하며 과거 완료 답변을 다시 생성하지 않는다. 기존 fallback 소스는 `agent/src/`에 남아 있으며 과거 스냅샷만 기존 카드로 표시한다.

frontend 기본 주소는 [http://localhost:5173](http://localhost:5173)다. `VITE_API_TARGET`의 `/api` 프록시로 backend에 연결한다. health 응답은 DB·저장소 모두 준비되면 `UP`이며 실패하면 HTTP 503을 반환한다. PostgreSQL volume, backend 원본 보관소, frontend 정적 파일은 서로 다른 역할이다. `bootRun` 기본 `./storage`는 `backend/storage/`에 해당한다. JAR를 다른 작업 폴더에서 실행할 때는 `KPLASMA_STORAGE_ROOT`를 원하는 절대 경로로 설정한다. 보관소와 DB를 같이 보존해야 불변 Run 버전과 원본 계보를 추적할 수 있다.

## Phoenix Cloud 추적

Phoenix Settings의 collector endpoint와 API key를 기존 `.env`에 추가한다. Space URL은 프로젝트 화면 주소의 `/s/<space>`까지만 사용한다. 프로젝트 이름은 Phoenix에 만든 이름과 같아야 한다.

```dotenv
PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/s/your-space
PHOENIX_PROJECT_NAME=K-PLASMA
PHOENIX_API_KEY=your-private-key
```

```sh
uv sync --project agent/python --frozen --extra tracing
npm run dev:agent
```

기존 worker는 종료하고 다시 실행한다. 시작 로그의 `Phoenix tracing ready: project=K-PLASMA`를 확인한 뒤 새 질문을 보낸다. Phoenix 프로젝트의 Traces/Spans에서 `agent.request`를 열면 그래프 노드, LLM 호출, backend context·checkpoint·최종 저장의 시간과 결과를 확인할 수 있다. `llm.responses`에는 프롬프트·입력 JSON·원문 응답·검증 결과·모델·추론 설정·토큰 수가 들어간다. 질문·문맥·Run 수치를 포함한 전체 노드 상태와 최종 답변을 설정한 클라우드로 전송한다. API 키와 내부 인증 토큰은 제외하며 opaque checkpoint 직렬화와 heartbeat polling은 수집하지 않는다.

`session.id`는 Agent 요청 ID다. 추가 입력이나 재시작은 같은 session에 새 실행 trace를 만들며, generation/revision·`kplasma.resumed`와 그래프·프롬프트 버전으로 당시 실행을 구분한다. `NEEDS_INPUT`은 정상 대기이며 오류로 표시하지 않는다. 수치 검증이나 모델 오류는 안전한 `error.code`로 표시한다. 관찰 코드는 상태·수치·최종 저장·복구 버전을 바꾸지 않는다.

HTTP/protobuf batch 전송이므로 매 노드가 Cloud 응답을 기다리지 않는다. 전송 장애가 분석 실패로 바뀌지는 않지만 추적 자체는 유실될 수 있다. 정상 종료에서는 대기 중인 추적을 flush하고, SIGKILL에서 trace 보존을 보장하지 않는다. 분석 복구는 기존 PostgreSQL 체크포인트가 담당한다. 잘못된 설정·의존성 누락은 `PHOENIX_CONFIG_INVALID` / `PHOENIX_SETUP_FAILED` 시작 로그로 확인한다. 추적을 끄려면 endpoint와 key를 둘 다 비우고 worker를 재시작한다. Phoenix 설정 변경은 기존 미완료 작업의 복구 fingerprint를 변경하지 않는다.

SDK/API 기준: [Phoenix OTEL 설정](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel), [수동 추적과 OpenInference](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument).

## 실제 150 Run 초기 적재와 재처리

실제 결과는 GitHub 밖에서 별도로 제공받는다. clone만으로 실험 데이터가 생기지 않으며 제품은 데이터를 자동 생성하지 않는다. 원본 `PRS_*/Source_*/Bias_*` 폴더 구조를 보존한다. 브라우저의 **도구 및 도움말 → Run 관리**에서 **폴더 선택**으로 원본 상위 폴더를 선택하거나 **ZIP 선택**으로 그 폴더를 담은 ZIP을 선택한다. 각 Run의 `0d_setting.ini`와 `0d_result/` 파일을 함께 유지한다. 압축해도 상대 계보는 유지되며 임의의 외부 래퍼 폴더는 표시용 파일 경로에 영향을 주지 않는다.

파일 접수 후 실제 바이트 전송률과 서버 처리 진행률을 확인한다. 정상 Run은 `READY`, 동일 원본은 `DUPLICATE`, 누락·손상은 `INCOMPLETE`/`PARSE_FAILED`로 나뉜다. 부분 성공 배치는 정상 Run만 검색 가능하다. 실패 항목을 선택하면 파일과 안전한 오류 위치를 확인할 수 있다. 외부 원본 업로드 한도는 폴더 2GiB, ZIP 컨테이너 2GiB, ZIP 해제 총량 2GiB, 5,000파일, 일반 파일 각각 64MiB다. ZIP 컨테이너 자체에는 64MiB 한도를 적용하지 않는다.

같은 source hash 재업로드는 중복이다. OS 메타데이터만 달라진 동일 idempotency-key 요청은 OS 파일을 제외한 canonical 파일 hash를 기준으로 기존 배치를 반환한다. 전체 전송 바이트의 동일성을 보장하는 계약은 아니다. 작업의 **다시 처리**는 같은 보관 원본으로 새 처리 시도와 성공 시 새 불변 버전을 만든다. 실패하면 이전 성공 버전을 계속 쓴다. 과거 대화와 판단 기록은 당시 버전을 참조한다.

**새 대화**는 대화·활성 Run·후보 참조와 진행 중인 Agent 요청을 비운다. **데모 데이터 초기화**는 여기에 판단 기록도 비운다. 두 동작 모두 업로드 원본·Run·그래프·불변 버전을 유지한다. 공용 서버·로그인은 이번 범위 밖이다.

## 등록한 Run 삭제

**도구 및 도움말 → Run 관리**에서 Run을 선택하고 **선택 Run 삭제**를 누른다. **전체 Run 삭제**는 검색 필터와 관계없이 등록된 모든 Run을 대상으로 한다. 확인창에서 대상 개수와 범위를 확인한 후 **삭제**를 눌러야 실행된다.

삭제는 해당 Run의 모든 버전·DB 수치·그래프·연결된 등록 작업과 프로그램이 보관한 원본 복사본을 정리한다. 처음 폴더 선택에 사용한 외부 원본 폴더는 변경하지 않는다. 다른 Run이나 남아 있는 작업이 공유하는 파일도 보존한다. 아직 Run으로 등록되지 못한 실패·불완전 항목은 이 기능의 대상이 아니다.

저장된 의견·판단 기록에서 사용하는 Run이 하나라도 있으면 요청 전체를 거부하고 대상 Run을 안내한다. 일반 채팅에서 조회하거나 후보로 표시된 Run은 삭제할 수 있으며 과거 채팅 스냅샷은 유지한다. 삭제 대상이 현재 Agent 기준 Run 또는 후보 집합에 있으면 해당 현재 선택만 자동으로 해제한다. 판단 기록을 없애도 되는 경우에는 **데모 데이터 초기화** 후 다시 시도할 수 있다. 업로드·재처리 중에는 완료될 때까지 삭제할 수 없다.

DB 삭제 후 관리 파일 정리가 끝나지 않으면 화면에 별도로 안내한다. 삭제한 Run은 검색에서 제외되며 다음 삭제 또는 서버 재시작 때 남은 파일 정리를 재시도한다. 같은 파일을 다시 선택해 새로 업로드하면 재등록할 수 있다. 과거 업로드 요청의 재시도가 삭제 데이터를 복구하지 않도록 기존 요청 키와 빈 배치 접수 기록은 유지한다.

Run 삭제는 일반적인 데이터 관리 기능이다. 이 작업을 위해 PostgreSQL volume이나 DB 전체를 초기화할 필요는 없다.

## 검증

```sh
npm test
uv run --project agent/python --frozen pytest agent/python/tests agent/python/evals
uv run --project agent/python --frozen ruff check agent/python/src agent/python/tests agent/python/evals
uv run --project agent/python --frozen mypy agent/python/src
npm run typecheck
npm run lint
npm run build
backend/gradlew -p backend test --console=plain
npm exec --workspace frontend -- playwright install chromium
npm run test:e2e
npm run test:agent:restart
npm run verify:public-files
```

Linux에서 브라우저 시스템 의존성이 없으면 `playwright install --with-deps chromium`을 사용한다. `test:e2e`는 인공 입력 3 Run을 만들고 독립 PostgreSQL·backend JAR·Python worker·Vite를 시작한다. 다섯 v1 답변, 정확한 Run 버전, 추가 입력 대기·resume·reload와 페이지 배치를 390/800/1008/1440px에서 검사한다. HTTP·그래프·체크포인트·수치 계산은 실제 구현을 쓰며 모델만 테스트 모듈의 고정 응답으로 대체한다. 이는 실제 LLM 품질 검증이 아니다. `npm run test:e2e:live`는 동일 흐름에 실제 `gpt-5.6-luna`/`none`을 연결하며 키와 API 사용량이 필요하다. 제품 worker에는 테스트 모델 선택 옵션이 없다.

DB는 테스트 전용 이름과 임의 localhost 포트로 생성하며 자기 컨테이너만 정리한다. 다른 개발 DB나 서버를 재사용하지 않는다. Gradle build 출력과 project cache도 실행별로 나뉘고 복사한 JAR로 서버를 실행한다. 기본 제품 서버의 Clock을 변경하지 않는다. v1 검증 결과는 Git에서 제외한 `agent/python/.runtime/`에만 보관한다. 질문·응답·체크포인트·trace·토큰이 포함될 수 있는 연결 파일을 게시하지 않는다.

`test:agent:restart`는 독립 인공 환경의 Spring 서버만 SIGKILL하고 같은 DB·보관소·포트로 다시 시작한다. 접수 상태, 추가 입력/checkpoint, 완료 답변과 같은 요청의 멱등 재개를 세 시나리오로 확인한다. 실제 그래프·HTTP·DB를 사용하고 모델만 고정 테스트 응답이며, OpenAI 호출은 없다. 기본 CI에도 포함한다.

`frontend/playwright.config.ts`와 `test:e2e:legacy`는 이전 fallback UI 검증을 보존한 역사적 실행기다. v1에서 같은 답변 문구·카드 구조를 요구하지 않으므로 현재 기본 CI 통과 기준으로 사용하지 않는다. fallback 순수 함수 테스트는 계속 `npm test`에 포함된다. 외부 원본 파싱·수치 비교용 `verify:reference`의 기존 전체 UI 단계도 이 역사적 검증 범위이며, v1의 실제 LLM 평가와 혼동하지 않는다.

인공 질문 140개를 모델별 세 번 평가하는 명령과 결과 판정 범위는 [Agent 평가 문서](../agent/python/evals/README.md)를 따른다. 프로세스 강제 종료 테스트는 `node scripts/agent/dev-verification.mjs --no-worker`로 독립 환경을 시작한 후 출력된 연결 파일을 `agent/python/.venv/bin/python scripts/agent/fault-verification.py --connection <파일>`에 전달한다. 이 환경에 다른 worker를 동시에 연결하지 않는다.

이미 검증한 Chromium을 명시할 때는 `KPLASMA_BROWSER_EXECUTABLE`에 실행 파일 경로를 넣을 수 있다. 보고서에 실제 browser.version을 기록하며 기준과 React는 같은 브라우저 컨텍스트의 폰트·ko-KR locale·Asia/Seoul 시간대·1배율·고정 시각을 사용한다. 개발자 개인 설치 경로는 소스에 하드코딩하지 않는다.

## 외부 기준 패키지

팀이 받은 원본을 읽기 전용으로 보존하고 저장소 밖에 별도 기준 패키지를 만든다. 경로는 팀원이 공급하며 특정 개인 폴더를 요구하지 않는다.

```sh
node scripts/reference/prepare.mjs \
  --prototype /path/to/original/prototype \
  --raw /path/to/original/raw \
  --tests /path/to/original/tests \
  --output /path/outside/repository/reference-v12.3.1
export KPLASMA_REFERENCE_ROOT=/path/outside/repository/reference-v12.3.1
npm run reference:check
npm run verify:reference
```

패키지는 `manifest.json`, `prototype/`, `raw/`, `tests/`를 포함한다. loader는 파일 목록과 SHA-256을 검증하고 원본을 수정하지 않는다. 기준 없이는 `verify:reference`가 필요한 환경변수를 설명하고 실패한다. 일반 `npm test`와 CI는 외부 비교 4건을 명시적으로 skip하며 인공 테스트만 실행한다.

외부 검증은 서로 다른 빈 DB에서 폴더 150 Run과 ZIP 150 Run을 각각 실제 파싱·등록하고 모든 scalar와 그래프, 가용성, 표시 파일을 정확히 비교한다. 검증 전용 생성 소스에서만 backend Clock을 고정한다. 원본에는 Git 이력이 없으므로 원본 commit은 `null`과 사유를 기록하고 버전·manifest checksum을 사용한다. 앱 HEAD·dirty 여부·파서 버전·런타임·assertion 수·ID별 상태도 기록한다. 결과가 PASS여도 D1–D5와 남은 차이가 별도 유예라면 전체 100% 동등성으로 해석하지 않는다. 상세 범위는 [수용 검증](verification/acceptance.md)과 [102 대응표](verification/prototype-test-map.md)를 읽는다.

실제 비교는 원본 약 1.4GiB와 두 보관소·ZIP·JAR를 위한 여유 디스크 및 수 분 이상의 시간이 필요하다. 모든 결과는 실행마다 고유한 `backend/.runtime/verification/<mode>-<timestamp>/`에 저장한다. Playwright 결과 경로를 재사용하면 지워질 수 있으므로 다른 실행 디렉터리를 사용한다. 로그·trace·스크린샷·JSON·원본·DB를 Git 또는 CI artifact로 올리지 않는다. 파일 guard는 휴리스틱이므로 PR diff도 확인한다.

기본 실행기는 성공·실패 후 자기 DB 컨테이너와 서버를 종료한다. 긴 외부 비교 중 브라우저 테스트를 진단할 때만 `KPLASMA_VERIFY_DEBUG_HOLD=true npm run verify:reference`를 사용할 수 있다. browser 실패 시 ignored `browser-env.json`에 비밀값 없는 테스트 URL/옵션을 남기고 자기 API/DB를 유지한다. 수정 후 Enter로 같은 등록 상태의 browser suite를 재시도하거나 `stop`을 입력해 정리한다. 최대 3회이며 시도마다 서로 다른 출력 경로와 상태를 기록한다. CI는 이 옵션을 사용하지 않는다. 별도 재등록 없이 보관된 결과의 메타데이터만 추출하려면 `node scripts/reference/browser-evidence.mjs /path/to/ignored/verification-output`을 실행한다.

## 정상 종료

backend와 frontend 터미널에서 각각 `Ctrl+C`를 누른다. DB는 다음 명령으로 멈추며 volume과 원본은 남는다.

```sh
docker compose stop postgres
```

일반 종료·초기화 절차에 원본 삭제나 DB volume 삭제를 포함하지 않는다. Java 테스트에는 Mockito 동적 agent/CDS 경고가 나올 수 있으며 결과와 함께 공개한다. 일부 Playwright 로그의 NO_COLOR/FORCE_COLOR 경고는 도구 환경 경고다. 테스트 실패·데이터 차이를 이 경고로 간주해 숨기지 않는다.

## 순차 PR 검토와 병합

이번 구현은 10개 순차 PR을 선행 PR 브랜치에 쌓아 증분 diff로 검토한다(PR2 base는 PR1 브랜치 등). 의존 feature 브랜치를 base로 둔 PR을 그 브랜치에 바로 병합하지 않는다. 선행 PR이 main에 병합되면 작성자/팀이 후속 브랜치를 최신 main 위로 다시 정리하고 base를 main으로 바꾼 뒤 병합한다. 브랜치 재작성은 [협업 가이드](../CONTRIBUTING.md)의 합의된 개인 브랜치 `--force-with-lease` 규칙을 따른다. 자동 retarget/rebase나 원격 브랜치 보호 활성화를 가정하지 않는다. 이 문서는 main 병합이나 push 권한을 추가로 부여하지 않는다.

### Python v1의 외부 원본 수치 대조

원본 프로토타입 폴더를 명시하여 `KPLASMA_PROTOTYPE_ROOT=/path/to/prototype npm run verify:agent-reference`를 실행한다. Node는 외부 원본의 순수 검색 함수를 검증용 oracle로만 실행하고, Python v1 결과와 비교한다. 제품 worker의 fallback/Node bridge 경로와는 관계없다. 원본 Run 값은 프로세스 메모리에서만 다루며 stdout에는 사례 수·실패 사례 번호·정책 차이·원본 파일 해시만 남긴다.

이 명령은 전체 exact 및 한 off-grid 순방향의 scalar 값/차이, 역방향 hard 조건과 min/max 목표의 후보·그룹·근접 순서를 대조한다. 계획 X5에 따른 비가용 값 제외는 원본의 null→0 암묵 변환과 의도적으로 다르며 별도 집계한다. soft 범위·엄격 부등호의 변경 정책은 인공 수치 테스트에서 검증한다. 전체 원본 화면/곡선 대조를 의미하지 않는다.

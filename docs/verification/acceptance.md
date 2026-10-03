# v12.3.1 수용 검증

2026-10-03 보관된 전체 Task12 로컬 gate는 **PASS_WITH_DEFERRED**다. 독립 리뷰 I1/I2 수정 후 전체 외부 등록을 반복하지 않았다. 기존 물리 비교는 유지하고, 신규 실제 HTTP/PostgreSQL 인공 memory 결과와 엄격한 evidence finalizer 회귀를 별도로 검증했다. 실행 시 앱 HEAD는 `d755f43`, 미커밋 검증 실행기/문서가 있으므로 `appDirty=true`로 기록했다. 실행 후 만들어질 커밋으로 테스트했다고 소급하지 않는다. 기준 원본 `v12.3.1` manifest SHA-256은 `d86440c3809dcccb5634d55160cd9cb423bdd75938279533f1a525ca0d735b69`이며 원본 Git 이력은 없다. 원본-source-only 테스트와 새 구현 assertion은 구별한다.

| Gate | 재현 명령 | 현재 상태 |
| --- | --- | --- |
| 인공 단위·계약·패키지·엄격 비교기 | `npm test` | PASS: frontend 76, agent 32 + 외부 4 skip, Node 28 (리뷰 수정 후) |
| TypeScript·lint·build | `npm run typecheck && npm run lint && npm run build` | PASS; E2E TypeScript도 검사 |
| 실제 PostgreSQL backend 회귀 | `backend/gradlew -p backend test --console=plain` | PASS: 98, 실패/오류/skip 0; 별도 build/cache 사용 |
| 실제 HTTP+DB 인공 전체 흐름 | `npm run test:e2e` | PASS: 10, 외부 기준 전용 6 skip (리뷰 수정 후) |
| 외부 폴더/ZIP 각각 150 Run | `npm run verify:reference` | PASS_WITH_DEFERRED: 각 150 READY·829,300 assertion·차이 0; 별도 빈 DB/보관소 |
| 공개 파일 검토 | `npm run verify:public-files` + PR diff | PASS: 금지 경로·실제 payload guard + 수동 diff 검토 |

최종 외부 실행은 150 Run·Bias-on 125·Bias-off 25·strict 6, summary 150·표시 파일 1,200개를 확인했다. 등록 시각도 고정 Clock으로 포함했다. 현재 ID coverage는 새 ESM 97개와 React 의미 assertion 5개로 102 PASS다. 구조 02는 기존 외부 실행에서 부분 검증이었고, 수정 후 별도 인공 실제 HTTP/DB memory 답변에서 container-type과 820/620 경계 전후 및 reduced-motion을 검증해 대체했다. 나머지 ID와 물리 비교는 보관된 외부 증거다. 이 합계를 신규 전체 외부 명령 성공으로 소급하지 않는다. 실제 browser 체크는 14 PASS·인공 UI 업로드 전용 1 skip이다. 14개 중 D1은 예상 HTTP 400을 확인하는 별도 안전성 검사이며 데모 호환성 PASS가 아니다. 같은 Chromium 149.0.7827.55, Playwright 1.63.0, darwin/arm64, ko-KR, Asia/Seoul, 1배율에서 기준/React Analysis 4탭과 Run 모달 7탭 SVG tree/좌표를 네 폭에서 정확히 비교했다. 폰트 stack은 `Inter, Pretendard, -apple-system, system-ui, Segoe UI, sans-serif`이며 같은 브라우저 컨텍스트의 같은 폰트를 쓴다. 이 머신은 명시적인 설치 headless-shell override를 사용했고 clean clone은 문서대로 Chromium을 설치한다.

실데이터는 외부 `KPLASMA_REFERENCE_ROOT`에서만 읽는다. `verify:reference`는 기준 SHA-256 검증, 각 빈 PostgreSQL에서 폴더/ZIP 등록, full immutable Run의 모든 필드/배열/순서/shape 비교, summary/catalog projection 확인, 새 ESM 라이브러리에 원본 97개 assertion 재실행, React 의미 검증 5개, 동일 Chromium 기준/React 그래프·레이아웃 비교, unmocked workspace/decision lifecycle을 연결한다. 등록 시각은 고정 Clock의 같은 instant로 비교한다. ISO offset 표현만 같은 정확한 instant로 인정한다. 새 immutable version UUID는 별도 유효성·안정성 검증 대상이며 원본에는 없는 identity만 physical 비교에서 제외한다. 그래프 수치 tolerance, 전체 snapshot 갱신, 실제 내용 masking은 사용하지 않는다.

`compare-tests.mjs`는 원본 테스트를 고치지 않고 require 경계에서 새 ESM 모듈을 공급한다. `buildForwardViewModel`의 명시적 Run 주입 인자만 새 라이브러리 계약에 맞춰 공급하며 원본 기대값은 유지한다. 이는 fallback 라이브러리 회귀 증거다. 구조 5개의 source-regex는 React DOM/키보드/로컬 요청/후속 질문 assertion으로 대체한다. 해당 ID별 명령·상태는 [대응표](prototype-test-map.md)에 있다.

CI에는 외부 패키지를 공급하지 않으며 인공 데이터·계약·backend PostgreSQL·browser 흐름만 실행한다. `.github/workflows/ci.yml`에는 artifact upload가 없다. 실제 원본·payload·수치 로그·대화·판단·DB·trace·화면은 Git/CI에 올리지 않는다. 기록하는 appCommit은 실행 시점 HEAD이며 appDirty도 함께 표시한다. 미래 커밋으로 실행했다고 소급하지 않는다. 원본 sourceGitCommit은 Git 이력이 없어 `null`이며 manifest checksum과 `v12.3.1`로 식별한다.

| 잔여 범위 | 상태와 해석 |
| --- | --- |
| D1 | DEFERRED: 원본 데모 EXP 4건에 채택이 없고 보통 EXP는 정확히 채택 1개를 요구한다. 실제 UI entry 오류를 별도로 검사하며 demo parity PASS로 세지 않는다. |
| D2 | DEFERRED: 다른 데이터 수에 대한 fixed150 문구·기본값 일반화는 하지 않는다. |
| D3 | DEFERRED: 동시 업로드 역순 완료의 강화된 최신 버전 정책은 추가하지 않는다. |
| D4 | DEFERRED: 비용 반려 재사용은 원본 display Run ID 범위를 유지한다. |
| D5 | DEFERRED: 추가 localhost/origin 접근 제어는 이번 범위 밖이다. |
| native source-files details | DISCLOSED_MINOR: 네 폭에서 별도 재현. 탭 전환 후 원본은 닫히고 React는 열린 상태로 남는다. 미해결 차이이며 전체 100% UX 동등성을 주장하지 않는다. |
| 800px Analysis 가로 넘침 | SOURCE_INHERITED: 같은 인공 데이터/상태에서 원본·React 모두 viewport 800px, scrollWidth 886px. 원본 보존에 따라 고치지 않고 양쪽 폭 일치를 검사한다. 무넘침 PASS로 세지 않는다. |
| 팀원 clean-clone 실제 실행 | 문서와 자동화 제공; 다른 팀원이 실제 실행했다는 증거는 아직 없다. |

이전 Task9/11 targeted Playwright 그룹은 같은 outputDir을 사용해 일부 그래프 화면·summary가 후속 실행에서 지워졌다. retained 통과 로그는 남지만 현재 화면이 보관되어 있다고 주장하지 않는다. Task12는 모든 실행의 고유 outputDir과 별도 summary를 사용한다. Mockito/CDS, 일부 Hikari 종료 및 NO_COLOR/FORCE_COLOR 경고는 보고서에 그대로 공개한다. 로컬 CI-equivalent 통과는 원격 GitHub Actions 실행 성공을 뜻하지 않는다.

레이아웃 bounding 좌표에만 최대 1/64px 차이를 허용한다(R18). 측정된 원본 selector x=355.609375와 React x=355.625의 정확한 차이에서 나온 fractional layout rounding이며 기존의 넓은 `toBeCloseTo` 허용은 쓰지 않는다. SVG 전체 tree·좌표와 실제 scalar/graph 값·shape·순서·개수에는 오차를 허용하지 않는다. 원본을 가리거나 실제 내용을 mask하지 않는다.

인공 CI 800px 검사는 플랫폼 폰트가 바꾸는 x좌표에 Mac의 886px를 강제하지 않는다. 고정 selector 폭 530px, 그 right의 ceil과 문서 scrollWidth의 정확한 일치, 실제 관측 폭을 기록한다. 외부 비교는 원본/React 문서 폭을 정확히 비교한다.

모든 실데이터 증거는 무시된 로컬 `backend/.runtime/verification/reference-1791020640641/`(최종 외부)와 `synthetic-1791020770166/`(최종 인공)에만 있다. 최종 외부 실행의 debug-hold 옵션은 활성화했지만 첫 browser 시도에서 통과해 대기/재시도는 없었다. 이전 실패는 test-only Clock bean 이름 충돌, Vitest의 Playwright 파일 잘못 수집, 잘못된 테스트 버튼 이름/실패 후 cleanup 누락, 실제 HTTP 탭 저장 완료 전 SVG 비교였다. 수정 후 390px scoped 원본/React 7탭을 먼저 확인했고 마지막 전체 실행에서 모두 통과했다. 추가 수치 tolerance나 product 수정은 없었다. 실제 CI 원격 실행, 다른 팀원의 clean clone, D2–D5 후속 정책은 미검증/유예다.

리뷰 수정 후 인공 composed 실행 `synthetic-1791023004790/`은 HEAD `c1da9d9`, `appDirty=true`에서 10 PASS·외부 전용 6 skip, evidenceValidation PASS다. 고정 viewport 1440px에서 실제 memory 답변 content-box를 821/820/819 및 621/620/619px로 조정하여 viewport media query와 분리했다. `.memory-answer`의 `inline-size`, summary 4/2/2열, row/column/column 및 stacked action 전체 폭, reduced-motion transition을 검사한다. 해당 [ID 대응표](prototype-test-map.md)의 P-structure-02에 연결된다.

mandatory browser report·browser/runtime/font metadata·정확한 unique 102 expected ID와 PASS status가 외부 gate에 없으면 전체 FAIL과 nonzero exit로 끝난다. 추출 실패도 모든 expected ID의 UNVERIFIED/FAIL diagnostics를 남긴다. 인공 실행의 외부 전용 P-structure-05는 실제 skipped case로만 별도 허용하고 PASS로 바꾸지 않는다. missing report/case/portable ID, duplicate ID, metadata 누락 및 실패 case 회귀가 이를 검증한다. 기존 외부 summary의 verdict/metadata를 수정해 새 실행으로 표시하지 않았다.

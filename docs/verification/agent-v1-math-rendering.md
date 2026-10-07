# Graph v1 일반 답변 수식 표시 검증

2026-10-08, `feat/agent-graph-v1`. 사용자가 승인한 일반 답변 수식 표시를 단독 구현했다.

## 변경

- 일반 답변의 Markdown에 `remark-math`와 `rehype-katex`, 동일 버전의 KaTeX CSS를 연결한다. 문장 안의 기호는 `$...$`, 별도 줄의 수식은 `$$`를 독립된 줄에 두어 작성하도록 일반 답변 프롬프트를 보강했다.
- 기존 `\(...\)`·`\[...\]` 답변은 표시할 때만 호환 변환한다. CommonMark 파서의 원문 위치로 코드·HTML·링크·이미지·링크 정의를 제외하며 일반 대괄호나 저장된 답변을 재작성하지 않는다.
- raw HTML 차단과 위험한 URL 차단을 유지하며 KaTeX의 `trust=false`를 명시한다. 잘못된 수식은 원문을 남기고 나머지 답변을 표시한다.
- 긴 수식은 수식 영역 내부에서 가로 스크롤한다. 일반 답변 컴포넌트를 지연 로딩하여 수식 엔진을 초기 화면의 필수 JavaScript에서 분리했다. 그래프·도구·API 계약과 LLM 호출 수는 변경하지 않았다.

## 검증

| 범위 | 실행 및 결과 |
|---|---|
| 실패 재현 | 수식 연결 전에 일반 답변 테스트의 4건이 실패했다. 실제 수식 노드가 생성되지 않는 원인이었다. |
| 컴포넌트 및 전체 JS 검증 | `npm test`: frontend 155건, TS agent 33건, 검증 도구 34건 통과. 외부 원본 전용 4건은 기존 명시 skip이다. 수식·분수·아래첨자·기존 구분자·코드/링크 보존·잘못된 수식·HTML/TeX 보안 경계를 검증한다. |
| Python | `cd agent/python`에서 `PYTHONPATH=src .venv/bin/python -m pytest tests evals -q`: 338건 통과. `.venv/bin/ruff check src tests evals`, `.venv/bin/mypy src` 통과. |
| 타입 및 lint | `npm run typecheck`, `npm run lint`: 통과. |
| 브라우저 | `cd frontend`에서 `npx playwright test --config src/features/agent/agent-v1.playwright.config.ts general-answer.pw.ts`: 4건 통과. 390/800/1008/1440px, ko-KR, Asia/Seoul, 1배율, 고정 시각. 인공 응답의 실제 수식·CSS·글꼴 적용, 영역 내부 스크롤, 페이지 넘침 없음, reload, 서버 쓰기 0회와 페이지 오류 0건을 확인했다. 390/1440px 스크린샷도 직접 확인했다. |
| 실제 모델 | `gpt-5.6-luna`, reasoning `none`으로 인공 개념 질문 1건을 실행했다. 별도 줄 수식 5개가 달러 구분자로 반환됐으며 모두 KaTeX 파싱에 성공했다. 기존 Phoenix 설정을 활성화하여 호출을 추적했다. |
| 빌드 | `npm run build`: 통과. 초기 JS 약 412KB, 일반 답변 지연 로딩 JS 약 430KB로 분리됐다. 분리 전 이번 변경의 단일 JS는 약 841KB였다. 파일 크기는 압축 전 minified 값이며 사용자 응답 속도 개선 측정값이 아니다. |

## 범위와 실행

브라우저 API는 인공 응답으로 대체했으며 실제 서버/DB/worker 전체 연결 시험을 새로 실행한 것은 아니다. 모델 질문 1건의 통과는 모든 수식이나 설명의 물리적 정확성을 보장하지 않는다. 실제 모델의 원문과 스크린샷은 Git에서 제외된 로컬 경로에만 보관한다. backend 변경은 없어 backend 테스트를 새로 실행하지 않았다.

새 일반 답변의 표기 규칙을 적용하려면 Python worker를 재시작한다. 기존 완료 답변은 원문과 스냅샷을 유지한 채 새 화면에서 표시한다. 새 설치 환경에서는 갱신된 잠금 파일로 `npm ci`를 실행한다.

이 검증 환경의 Node는 22.19.0, npm은 10.9.3으로 저장소의 고정 버전(22.23.3/10.9.9)과 차이가 있다. 설치 시 engine 경고가 있었으며 위 검증은 현재 환경에서 통과했다.

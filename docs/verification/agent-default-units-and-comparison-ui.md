# 기본 단위와 비교 UI 후속 검증

2026-10-07 사용자 승인에 따라 단위 생략 시 재질문 정책을 기본 단위 적용으로 변경했다. 이전 [Tool Calling 검증](agent-v1-tool-calling-and-answers.md)은 당시 정책의 역사적 기록이다. 수치 엔진과 고정 그래프의 도구 네 개는 유지한다.

## 변경과 원인

- 수치 단위가 없으면 LLM은 null을 반환한다. 원문·추가 입력에 숫자와 조건이 연결되는지 확인한 뒤 코드가 압력 mTorr, 소스·바이어스 W, 평균 이온 에너지·IED 폭 eV, 이온 플럭스 10¹⁸ m⁻²s⁻¹를 적용한다. 플럭스 400은 이 표시 단위에서 400이며 SI 값 400으로 해석하지 않는다. 명시 단위는 우선하고 미지원·물리량 불일치는 HITL로 확인한다. 정렬만 요청하면 적용 단위 안내를 만들지 않는다.
- 선택 모델이 방금 제안한 인자를 이미 승인된 과거 해석으로 검증에 다시 넘기는 경로를 수정했다. 검증 실패한 제안도 다음 재개에서 신뢰된 문맥으로 승격하지 않는다. 질문에 없는 조건·숫자 추가와 단위 배율 추정을 차단한다.
- 적용 내역은 `AnswerSnapshotV2.unitAssumptions`로 저장한다. Python·Java 검증, TypeScript 계약과 공통 인공 fixture·OpenAPI를 함께 갱신했다. 기존 schema 2에서 필드가 없는 답변과 schema 1 답변은 안내를 새로 추정하지 않는다. 입력창의 기본 단위 도움말과 저장 답변의 안내를 제공한다.
- Run 선택 checkbox에 공통 `input {width:100%;min-height:42px}` 규칙이 적용됐다. 인공 DOM에 실제 CSS를 적용한 390px 브라우저 측정에서 checkbox 너비 340px, 텍스트 너비 0px, 행 높이 1358px로 재현했다. checkbox를 18px로 고정하고 텍스트에 남은 영역을 배정했다.
- 표와 반복되는 관찰은 `계산 근거`를 접어서 보존하고, UUID·데이터 상태도 상세 영역으로 옮겼다. 기준 없는 pair는 절대 차이와 양방향 표기를 사용한다. trend의 인접 변화량·변화율은 전역 기준이 없어도 표시한다.
- “기준 Run과 선택한 Run”은 기준 선택이 필요한 요청이다. 모델이 임의로 첫 Run을 기준으로 지정하면 선택을 요구한다. 확정 기준과 다른 별칭의 기준 역할을 답변에서 탐지하면 한 번 보완을 요청한다. 숫자 없는 모든 의미 오류를 판정하는 검증기로 표현하지 않는다.

## 검증 결과

모든 실행 데이터는 인공 Run이며 상세 응답·Phoenix trace·스크린샷·실제 키는 Git에서 제외한 로컬 경로에만 보관했다. 사용자의 실제 데이터와 운영 대화는 수정하지 않았다.

| 범위 | 명령과 결과 |
|---|---|
| Python 그래프·단위·재개·비교·harness | `agent/python/.venv/bin/python -m pytest -q agent/python/tests agent/python/evals`: **338 통과** |
| 서버 계약·HTTP·DB·상태 | Java 21에서 `backend/gradlew -p backend test --console=plain`: **153 통과 / 17 suite**, 실패·오류 0 |
| JavaScript·화면 계약 | `npm test`: frontend **150 통과**, agent **33 통과 / 4 skip**, scripts **34 통과** |
| 실제 모델 전체 그래프 | `PYTHONPATH=agent/python/src:agent/python agent/python/.venv/bin/python -m evals.run_acceptance --repeat 1 --concurrency 3`: **22/22 통과**, `gpt-5.6-luna` / `none`, Phoenix 활성 |
| 실제 HTTP·DB·worker·브라우저 | `KPLASMA_V1_LIVE_WIDTHS=1440 node scripts/agent/verify.mjs --live`: **2/2 통과**, 네 도구·단위 생략·선택·추가 입력·모달·reload 및 layout geometry |
| 네 폭의 브라우저 | `node scripts/agent/verify.mjs`: **5/5 통과**, 실제 서버와 고정 모델 test double, 390/800/1008/1440px |
| 정적 검사·빌드 | `npm run typecheck`, `npm run lint`, `npm run build`, Ruff·Mypy·`npm run verify:public-files`: 통과 |

브라우저 검증에는 실제 선택 컴포넌트의 checkbox 너비·높이 24px 이하, 텍스트 영역이 행 너비의 65% 초과, 행 높이 180px 미만이라는 회귀 조건을 추가했다. 단순 페이지 overflow 검사만으로 발견되지 않던 깨짐을 직접 검증한다. 체크 상태·선택 칩·필수 기준·표의 수평 스크롤·상세 모달·저장 안내의 재열람을 확인하고 390px 선택 화면과 1440px 비교 화면을 직접 읽었다.

전체 그래프 22회는 LLM 호출 36회, 입력 100,124 / 출력 4,749 토큰이었다. 단위 정책 변경으로 불필요한 단위 추가 입력을 없앴지만 이전 구현과 동일 조건의 비용 A/B 시험은 수행하지 않았다. 과학적 설명의 진위는 이 수치로 보장하지 않는다.

최종 프롬프트에서 단위 생략·기준 선택·미지원 단위·일반 답변을 추가로 5회 확인했다. 엄격한 최초 인자 추출 기준은 **4/5 통과**였다. 미지원 `psi` 한 건에서 모델이 단위를 null로 반환해 정답 인자와 달랐다. 그래프는 원문의 명시 단위를 감지해 조회 전에 `MISSING_UNIT`으로 중단했고, 사용자가 eV로 확인한 후에만 조회했다. 안전한 차단·재개는 통과했지만 모델 추출까지 전부 성공했다고 기록하지 않는다. 추가 5회는 8번의 LLM 호출이며 Phoenix로 추적했다.

## 적용

그래프 빌드는 `v1-2026-10-07.tool-2`, 프롬프트 버전은 `tool-selection-2`다. 서버·Agent를 새 코드로 재시작하고 frontend를 새로 열어 적용한다. 버전이 다른 미완료 요청은 새 질문으로 제출하고 완료 답변은 재생성하지 않는다. DB 마이그레이션이나 fallback 활성화는 필요하지 않다. 단독 검토를 수행했으며 팀원의 PR 승인은 별도로 필요하다.

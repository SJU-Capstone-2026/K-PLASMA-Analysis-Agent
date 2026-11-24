# d1 지시서 3단계 재배치 — 같은 정상5·오류5 전후 비교

2026-11-16, Asia/Seoul. **재구성안은 정확한 오류 항목·사유 검출이1/5→0/5로 낮아져 채택하지 않았다.** 정상5개는 계속 통과했지만 오류5개도 모두PASS했다. 기존 지시서·환경·같은 worker를 복원했고, 그래프·응답 양식과 실제 데이터는 변경하지 않았다.

| 지표 | 기존 | 재구성안 |
|---|---:|---:|
| 정상 계획 PASS |5/5|5/5|
| 정확한 오류 항목·사유 |1/5|**0/5**|
| 오류 계획의 잘못된 PASS |3/5|**5/5**|
| 오류 계획 UNCLEAR |1/5|0/5|
| 전체 계획 엄격 일치 |6/10|5/10|
| 검사 단위 정답 |57/62|57/62|
| 검사당 입력 |2140.89|2202.89|
| 계획당 모델 score 평균 |8.296초|8.597초|

## 변경한 것과 보존한 것

- 후보는 영어 계획 검토 지시서를 **1. Core check → 2. Valid cases → 3. Decision**으로 구분했다. 공통·13종 검사별 기존 규칙/예외 문장은 하나도 삭제하거나 고쳐 쓰지 않고 해당 단계에 재배치했다.
- 세 단계 제목과 공통 판정 절차를 추가했다. 정상 인정 조건이 별개 불일치를 허용하지 않으며, 해당 항목이 일치하면match·불일치면해당오류·제공된문맥으로판정불가하면unclear를 고르도록 했다.
- 따라서 이 실험의 변경 단위는 **문장 재배치+구조 제목+공통 판정 문구**다. 순서 하나만의 독립 인과 효과로 해석하지 않는다. gt/gte 설명 추가·문장 번역·범위 규칙 수정은 섞지 않았다.
- `state` 문자열, 원문 질문·이력·원본 계획·실행 효과·도구/지표 설명·정책, 선택지 ID/설명/순서, 검사 ID·검사 위치는 기존과 같다. 62개 native state 바이트와 state token prefix·선택지 token 그룹·보정값이 모두 같음을 확인했다.
- 답변 검토 지시서, 모델/정밀도/엔진·검사별 독립 단일 처리, 기존 그래프·PlanDraft·최종 응답·SSE·재계획2/재작성1 예산은 유지했다.
- 후보 버전 `d1-wire-en-ordered-2`는 미채택이다. 공용 버전은 **d1-wire-en-compact-1 / Q8+MLX / per_check**로 복원했다.

[실제 재구성안 전체 규칙](2026-11-16-d1-ordered-instructions-candidate.json)은 검토용 자료이며 제품에서 로딩하지 않는다. 공통3단계와13종류별 단계 문구를 그대로 보관했다.

## 같은 조건과 실행 범위

기준은 v2.4 코드 commit23b74dd3dc1fab5d4272d55730949688c4c612b6과 직전 같은 세션의 Q8 비교다. 기존 Q8 선택/확률이 과거 v2.4와도 완전히 같음을 확인한 기록을 재사용했고 기준 모델을 다시 호출하지 않았다.

정상5/오류5의 같은 frozen corpus SHA는 `c27853259c724b75e8851af094974b5b3b4ef0256c728f8182510e1136a98c87`이다. 질문·계획·정답표·검사순서·선택지는 고정했다. 새 모델 실행은 **후보10계획·62개 singleton forward 1회씩**이다. 숨은warmup·자동재시도·추가모델대조·Qwen·상용호출·새웹문항평가는 없다.

| 환경 | 적용값 |
|---|---|
| 호스트 | M4 Pro·통합24GiB·macOS Apple Silicon |
| d1 모델 | LiquidAI/d1-2B revision a6bce774e6dde338dcc3036ceb5d91f78bf4c19e, 기존 MLX affine8/group64·일부BF16 |
| 실행 | MLX0.32.4, mlx-decision1.3.0 commit2527a733c97a3fd5e0de54ea19f74fd362ed1ad2, Python3.12.15, Metal GPU |
| 검토 | group_size1/independent_batch_size1, en-compact-no-view·per_check, 계획별 프로세스 종료/모델 해제 |
| 입력 | 검사별16000 이하, 기존132735→후보136579토큰, 절단 없음 |
| 검토 상태 | 모델 설정과 실제 graph state의 plan_review_enabled=true 확인 |
| Docker·메모리 | VM1536MiB, development. warning 기록 허용·critical/unknown 중단, 0.5초 표본 |
| 공유 앱·저장 | 웹5173/backend8080/기존 DB/storage, 로컬 worker만 잠시 대기·같은PID 재개 |

비교는 고정 계획의 최초 검토이며 Qwen 새 계획·도구/Run 조회·REPLAN 복구·최종 사용자 답변을 새로 실행한 평가가 아니다. 실제 검사는9종류이며 나머지4종류는 이번 corpus에 없어 모델 정확도를 추가로 확인하지 않았다. 문장 보존 테스트는13종 전부를 검사했다.

## 판정과 사유 차이

62개 선택 중60개는 같고 아래2개가 바뀌었다.

| 사례/검사 | 정답 | 기존 | 재구성안 | 해석 |
|---|---|---|---|---|
| P08.bad / trend_axis.compare |match|unclear|match|불필요한 경향축 지적은 사라졌으나 실제 대상 오류는 계속 놓침. 전체상태UNCLEAR→PASS |
| P10.bad / ordering.search |direction_changed|direction_changed|match|기존에 찾던 정렬 방향 오류를 새로 놓침. 전체상태ISSUE→PASS |

P10.bad의 direction_changed 확률은50.17%→36.72%, match는37.31%→48.56%였다. 원시 선택부터match였고 기존 normalize_response/parse_plan_review도 같은 판정을 재현했다. 응답 파싱이 오류를 지운 것이 아니다.

경계·수치·대상·기준 변경4개는 이전과 같이 놓쳤고, 새로 정렬 방향까지 놓쳐 오류5개가 모두PASS했다. 검사 단위 정답57/62가 같아도 오류 검출이 나빠진 이유는 P08의 부수 오판1개를 고친 대신 P10의 실제 오류 검출1개를 잃었기 때문이다.

## 시간·토큰·메모리

입력은총3844토큰, 검사당62토큰 늘어 **2.90% 증가**했다. 이는 제목·공통 판정 문구의 비용이며 원문/계획 자료를 추가한 것이 아니다.

모델score 평균은8.296→8.597초, 관측상 **3.63% 증가**다. GPU 완료를 동기화한 실제 score 시간이며 모델로드·프로세스시작·count·준비·웹대기는 제외한다. 기존gateway의8.928초나 전체채팅시간과 같은 지표가 아니다. 기존값은 직전 기록이며 반복/순서반전 없는 단회 대조이므로 일반 속도 개선율로 쓰지 않는다.

새 평가의 OS active+wired+compressed 관측 피크는 **16.326GiB**, warning/critical/unknown0, 추가swap0, Docker/DB OOM변화0이었다. 서로 다른 회계의 RSS·MLX allocator·OS 피크를 합산하지 않는다.

## 소프트웨어 검증·채택 판단·복원

- 기존 규칙/예외의 문장 단위 golden 보존, 단계 순서, 새 지시서 버전, 선택지/답변 지시서 불변, 인공 입력8개 fingerprint를 테스트했다. 변경 전 **2실패/8통과**, 변경 후 관련 **60통과**.
- 후보 소스 상태의 전체 Python **1581통과/초기복제8제외**, 변경범위Ruff 통과. 소프트웨어 계약 통과와 실제 모델 정확도를 분리한다.
- 실행 전 정한 기준은 정상5/5, 오류사유최소1/5, 엄격계획최소6/10, 기존에 맞힌 검사에서 새 오판이 없을 것이다. 후보는 세 가지 정확도 조건에 실패했다.
- 후보 source/manifest/test/fixture는 비공개 로컬 기록에 보존했다. 제품 source/manifest는 변경 전 바이트로 복원하고 후보 전용 테스트는 실험 기록으로 옮겼다. 미사용 후보를 제품에 남기지 않았다.
- 복원 후 전체 Python **1571통과/초기복제8제외**. 원래 모델/서비스·환경·기존 메모리 증거·실제graph검토ON·sourceidentity·DB hash를 확인하고 같은worker PID19246을 재개했다. 추가 메모리7행·worker 준비 추론은 필요하지 않아 **0회**다.

원시입력·선택지확률·모델결과·비공개env는 `.local/runtime/v2.5-d1-instructions-order/`에만 보관한다. 핵심 파일은 plan.json, instruction-contract.before.json, wire-verified.json, packing.log, evaluation.json, analysis.json, production-parser-results.json, decision.json, restored-verified.json과 red/green/full/restored 검사 로그다. 후보 source와 테스트도 같은 경로에 따로 남겼다.

이 결과는 이번 재구성안이 정확도를 개선하지 못했다는 증거다. 모든 지시서 개선이 불가능하다거나 입력 표현·모델 자체 중 어느 하나가 최종 원인이라는 증거는 아니다. 추가 변형·다른 모델·40문항·웹 평가는 자동 실행하지 않았다. commit/push/tag/배포도 하지 않았다.

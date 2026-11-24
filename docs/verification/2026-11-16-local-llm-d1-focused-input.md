# d1 입력 자료 축약 — 지시서·선택지 고정 전후 비교

2026-11-16, Asia/Seoul. **정상5/5를 유지하고 정확한 오류 항목·사유 검출은1/5→2/5로 개선됐다.** 검사당 입력은13.23%, 계획당 모델score 시간은 관측상13.59% 줄었다. 경계·대상·기준 오류3개는 여전히 놓쳤다. 이번 변경은 비교 전용 입력 뷰이며 공용 worker의 입력 정책에 적용하지 않았다.

| 지표 | 기존 Q8+MLX | 입력 축약 Q8+MLX |
|---|---:|---:|
| 정상 계획 PASS |5/5|5/5|
| 정확한 오류 항목·사유 |1/5|**2/5**|
| 오류 계획 ISSUE |1/5|2/5|
| 오류 계획의 잘못된 PASS |3/5|3/5|
| 오류 계획 UNCLEAR |1/5|0/5|
| 전체 계획 엄격 일치 |6/10|7/10|
| 검사 단위 정답 |57/62|59/62|
| 전체 입력 토큰 |132,735|115,177|
| 검사당 평균 입력 토큰 |2,140.89|1,857.69|
| 계획당 평균 모델score |8.296초|7.169초|
| 검사당 평균 모델score |1.338초|1.156초|

## 기준과 범위

기준은 v2.4 commit `23b74dd3dc1fab5d4272d55730949688c4c612b6`의 기존 지시서 `d1-wire-en-compact-1`이다. 미채택된 지시서 재구성안의 오류 검출0/5를 기준으로 사용하지 않았다. 직전 엔진 비교의 원래 Q8 결과를 재사용했으며 기준 모델을 다시 호출하지 않았다. 그 결과는 기존 v2.4와 선택·확률도 같음을 앞서 확인했다.

같은 정상/오류5쌍의 frozen corpus SHA는 `c27853259c724b75e8851af094974b5b3b4ef0256c728f8182510e1136a98c87`이다. 질문·원본 계획·정답표·검사 순서를 바꾸지 않았다. 후보10계획의 **62개 singleton forward를 한 번씩** 실행했다. 숨은warmup·추가변형·자동재시도·Qwen·상용모델 호출은0회다.

고정 계획의 최초 검토 비교다. 새 Qwen 계획 생성·Run 조회·REPLAN 복구·최종 사용자 답변·새 웹/API 문항을 실행한 결과가 아니다. 모델 검사는9종류였고, 입력 투영의 CPU 검증은13종 전체를 대상으로 했다.

## 그대로 둔 것

- 기존 공통·검사별 지시서 문자열, 검사ID/순서/Check location, 선택지ID·설명·순서·token 그룹·보정값은 같게 유지했다.
- 원문 question, input_history, confirmed_context, 기존 선별 tool_contracts 전체, policy_context, completed_steps는 값 그대로 보존했다. 코드가 질문에서 기대값·정답·오류 여부를 추출하거나 만들어 넣지 않았다.
- 원본 계획·그래프 노드/간선·실제 실행 인자·도구·PlanDraft·JSON/SSE 응답·저장 계약은 미수정이다. 답변 검토, d1 ON, 요청 전체 재계획 최대2회·필요한 답변 재작성 최대1회도 유지했다.
- Q8·MLX·Metal, group_size1/independent_batch_size1, 영어축약·검사별 도구 설명 선별과 Docker1.5GiB를 유지했다. 새 모델·번역·few-shot·판정 임계값 변경을 섞지 않았다.

## 줄인 입력 자료

새 투영 `execution-data-focus-v1`은 기존 v2.4 선별 입력의 state 자료에만 적용했다. 실제 실행에 사용하는 계획은 손대지 않고, d1이 보는 복사본만 줄였다.

1. 여러 검사의 check_specs 중 현재 검사1개만 남겼다. native 질문은 원래부터1개였으며 모든 검사 자체는 그대로 실행했다.
2. requirements의 중복 text·sources는 보내지 않고 id·handled_by 연결을 남겼다. 실제 인자에 붙은 source.quote 복사본도 제외하되 source.message_key와 수치·단위·연산자·참조는 보존했다. 원문 질문과 이력은 계속 제공한다.
3. 필수3종(tasks/filter_coverage/confirmation_coverage)은 누락을 찾는 데 전체 단계가 필요하므로 모든 실제 실행 단계를 남겼다. 나머지는 현재 검사 단계와 depends_on·result_ref·guards·target_step_id로 연결된 단계를 전이적으로 보존했다. 미래 확인 단계가 검사 대상의 null 입력을 채우는 연결도 포함했다.
4. 관계없는 단계는 id·kind·tool/operation/confirmation·depends_on·requirement_ids만 남기고 inputs를 제외했다. steps 배열 길이·순서·ID는 유지해 지시서의 원래 위치가 다른 인자를 가리키지 않게 했다.
5. program_effects는 남긴 단계의 기존 문자열만 사용하고, 관계없는 효과와 plan_revision/prompt_version 추적 메타데이터를 제외했다. 질문을 해석한 새 요약이나 새 해설은 추가하지 않았다.

예를 들어 압력 필터를 검사할 때 원문 질문, 실제 pressure 연산자·값·단위, 관련 검색 단계와 기존 도구/정책은 남긴다. 같은 질문을 다시 인용한 요구사항 문구, 다른 검사의 위치 목록과 관계없는 설명 단계의 상세 입력은 뺀다. “정답은0.008이어야 한다” 같은 코드 생성 정답 힌트는 넣지 않았다.

도구 설명·정책은 동결했으므로 완전히 최소화된 두 줄 입력 실험은 아니다. 이번13.23%는 실행 자료와 중복 문구를 줄인 범위의 결과다. 개별 삭제 항목마다 따로 대조한 실험도 아니므로 특정 필드 하나의 인과 효과로 단정하지 않는다.

## 오류 항목과 사유

| 사례 | 실제 인공 오류 | 기대 사유 | 기존 | 축약 |
|---|---|---|---|---|
| P05.bad | 포함 경계gte→엄격 경계gt |boundary_changed|match·놓침|match·놓침|
| P06.bad | 원문0.008 Torr→실제8 Torr |value_changed|match·놓침|**value_changed·검출**|
| P08.bad | 검색 결과 전체→기존 선택 Run |target_changed|match·놓침|match·놓침|
| P10.bad | 높은 순→낮은 순 |direction_changed|direction_changed·검출|direction_changed·검출|
| B01.bad | 기준 Run 참조 변경 |target_changed|match·놓침|match·놓침|

62개 선택 중60개는 같고,2개가 바뀌었다. 기존 정답을 새 오답으로 바꾼 검사는0개다.

- P06.bad/filter.search.pressure: match→value_changed로 수정됐다. value_changed 확률7.45%→48.74%, match71.82%→19.89%였다.
- P08.bad/trend_axis.compare: 오류와 무관한 unclear→정답match로 수정됐다. match33.63%→70.75%였다. 정작 targets.compare의 오류는 여전히 놓쳤으므로 이 계획은UNCLEAR→잘못된PASS가 됐다. 이것을 올바른 대상 오류 검출로 세지 않는다.

검사 단위59/62에는 정상이어야 하는 검사57개가 포함된다. 오류를 찾는 성능은 정확한 항목·사유2/5로 따로 판단한다. 사유는 d1의 선택지 분류이며 자유 서술형 추론 설명을 새로 생성한 것이 아니다. 기존 normalize_response/parse_plan_review가 원본 전체 계획에 대해 같은 판정과 근거를 재현했다. 파서 변경으로 만든 개선이 아니다.

입력 표현만 바꿔도 수치 오류의 판정이 달라질 수 있음을 확인했다. 이 결과가 모델 자체의 한계를 배제하지는 않으며, 남은3개 오류의 근본 원인을 확정한 것도 아니다.

## 시간·메모리·환경

총17,558토큰, 검사당283.19토큰 감소했다. 모든 실제 입력이16000 이내이고 최대2,785토큰으로 절단은 없었다.

시간은 GPU 완료를 동기화한 score 합계/10계획이다. 모델로드·프로세스시작·토큰 수 계산·메모리 준비·웹 대기는 제외했다. 기존 gateway의8.928초나 전체 채팅 시간과 직접 비교하지 않는다. 기준은 기존 기록이고 반복·순서반전 없는 단회 관측이므로13.59%를 일반적인 속도 개선율로 단정하지 않는다.

| 환경·관측 | 값 |
|---|---|
| 호스트 | M4 Pro·통합24GiB·macOS Apple Silicon, 다른 앱 임의 종료 없음 |
| d1 | LiquidAI/d1-2B revision a6bce774e6dde338dcc3036ceb5d91f78bf4c19e |
| 정밀도 | 기존 MLX affine8/group64, Linear153개 Q8·embedding/norm/conv BF16 유지 |
| 실행 | Python3.12.15·MLX0.32.4·mlx-decision1.3.0 commit2527a733c97a3fd5e0de54ea19f74fd362ed1ad2·Metal |
| 검토 | 설정·실제 graph state plan_review_enabled=true, singleton1, en-compact-no-view/per_check, temperature1.337398453966105 |
| 해제 | 각 계획 별도 프로세스·검사 순차 처리·계획 완료 후 프로세스 종료 |
| Docker | VM1536MiB, MemTotal1,538,883,584bytes, DB OOM0→0 |
| 메모리 정책 | development, warning 기록 허용·critical/unknown 중단 |
| OS 메모리 관측 피크 | active+wired+compressed **17.870GiB**,0.5초 간격 등 총177표본 |
| 압력·swap | warning/critical/unknown0, 추가swap0. 기존swap 자체가0이라는 뜻은 아님 |
| 공용 서비스 | 웹5173/backend8080/기존DB·storage 유지. 유휴 로컬worker19246 정지·재개 후 종료를 확인해 같은 설정의 새worker40971로 복원 |

OS 전체 피크를 d1 전용 메모리로 해석하지 않으며, 다른 시점의 전체 OS 피크와 비교해 메모리 개선율을 만들지 않는다. RSS·MLX allocator와 합산하지 않는다. Qwen 설정·생각모드·캐시 상태와 기존 공용 메모리 준비 증거는 그대로다.

## 검증·보관·현재 상태

- 축약 미구현 상태의 CPU 테스트2실패를 확인한 뒤 구현했다. 최종 CPU 테스트3통과: 같은62개 입력의 지시서/자료 보존·크기 감소,13종 검사 위치/인자 보존, 전이 참조/미래 확인 연결 보존.
- 실제 토크나이저로62개 모두 선택지token 그룹·보정값 동일, 토큰 감소·입력 절단 없음 확인. 사전 token 검사는 모델 forward0회다.
- 모델 결과62개를 기존 정규화/계획 검토 파서로 읽어 실제 항목·사유·근거 전달을 확인했다.
- 비교 전·중·후 source identity와 DB snapshot hash, worker env, Docker 한도와 OOM 보존을 확인했다. 모델·웹·backend 프로세스는 그대로이며 로컬worker만 아래 기록과 같이 교체했다.
- 이 비교의 정확도 비퇴행 기준(정상5/5·오류사유최소1/5·엄격계획최소6/10·기존 정답의 새 오판0)을 충족했다. **비교 전용이므로 제품 입력 정책은 미변경**이다. 아직 일반 정확도 보증이나 v2.5 완료로 기록하지 않는다.

실행과 원시 증거는 Git 제외 `.local/runtime/v2.5-d1-focused-input/`에만 보관한다. focus.py/test_focus.py/prepare_inputs.py, plan.json, wire-verified.json, inputs.json, packing-verified.json, engine_probe.py/run_evaluation.py, evaluation.json, analysis.json, production-parser-results.json, decision.json, restored-verified.json, worker-exit-diagnosis.json, replacement-worker.json, restore-ready.json, final-runtime-verified.json과 red/green 로그가 있다. 원문·확률 전체·env·가중치를 이 공개 문서에 복사하지 않는다.

재현 검증은 위 폴더의 test_focus.py에 대해 `PYTHONPATH=.local/runtime/v2.5-d1-focused-input:agent/python/src:agent/python:agent/python/tests agent/python/.venv/bin/python -m pytest .local/runtime/v2.5-d1-focused-input/test_focus.py -q`를 실행한다. 실제 추론 실행기는 기존 결과가 있으면 자동 반복하지 않으며 유휴worker·메모리·설정 검증을 요구한다.

## 공용 워커 복원과 별도 연결 검사

처음 복원 절차는 같은worker19246에 SIGCONT를 보냈지만, 최종 생존 확인에서 그 프로세스가 종료됐음을 발견했다. 로그는 `LOCAL_RUNTIME_NOT_READY:LOCAL_RUNTIME_PROFILE_MISMATCH`였다. 현재 runtime_profile·live_facts를 원래 worker의 시작 기록과 다시 비교한 결과 모두 같았고 기존 메모리 증거도 유효했다. 실제 설정 차이는 발견되지 않았다. 지문 확인 내부의 어느 조회가 실패했는지 로그가 보존하지 않아 정확한 내부 원인을 확정하지 않는다. SIGCONT 전송 성공만으로 정상 복원이 완료됐다고 판단한 일차 기록은 final-runtime-verified.json으로 정정했다.

같은 설정·모델·원래 worker 로직으로 새PID40971을 시작했다. 준비 검사는 원래의 상한4회를 유지했고 **Qwen 인공 연결3회·d1 인공 연결1회**를 실행해 ready=true·blockers=[]를 확인했다. 검토 정확도 평가를 다시 실행하거나 준비 검사를 우회하지 않았다. 재시작 후 생존·원래 모델/웹/backend 프로세스·메모리 증거·d1 해제·실제graph검토ON·Docker 한도·DB/source/env 보존을 재확인했다. 워커가 종료된 일은 완료된62개 비교 결과와 평가 중 메모리 집계를 바꾸지 않는다.

제품 소스가 바뀌지 않아 전체 제품 테스트·웹40문항·추가 모델 대조는 재실행하지 않았다. commit/push/tag/배포도 하지 않았다. 앞선 엔진/지시서 실험과 합친 v2.5 **의미 검토 비교는314회 forward 시도·완료 결과310개**다. 별도 워커 연결4회를 더하면 전체 모델 호출 시도는318회다. 이번 작업만은 후보62회+워커 연결4회=66회, 기준 신규호출0회다. 앞선 불완전 계획의4회 시도를 숨기거나 완료로 합산하지 않았다.

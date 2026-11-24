# d1 공통 지침의 검사 범위 한정 — 같은 실제 Qwen 계획 전후 비교

2026-11-17, Asia/Seoul. **이번 문구는 미채택이다.** 바이어스 사례의 잘못된 작업/필터 누락 지적은 없어졌지만, 실제 숫자 오류를 놓치는 문제는 그대로였다. 확인 요청 누락 검사의 UNCLEAR가 늘어 정상 통과가5/5→1/5로 떨어졌다. 공용 제품 소스·프로필은 처음부터 변경하지 않았다.

| 지표 | 기존 | 범위 한정 문구 |
|---|---:|---:|
| 정상 계획 PASS |**5/5**|**1/5**|
| 실제 오류 항목 검출 |3/5|3/5|
| 오류 항목·value_changed 사유 모두 정확 |2/5|2/5|
| 오류 계획 전체 ISSUE |4/5|3/5|
| 오류 계획 UNCLEAR |0/5|2/5|
| 오류 계획의 잘못된 PASS |1/5|0/5|
| 모든 검사 항목·사유까지 엄격 일치 |5/10|1/10|
| 검사 단위 정답 |44/56|43/56|
| 오류 사본의 부수 오판 |9|6|
| 정상 계획에 생긴 오판 |0|4|
| 전체 계획의 부수 오판 |9|10|
| 검사당 입력 |2,200.29토큰|2,233.29토큰|
| 계획당 모델score 평균 |7.682초|7.813초|

기준은 [직전 실제 Qwen 정상5·오류5 평가](2026-11-17-local-llm-d1-real-qwen-contrast.md)다. 기존56개 결과를 재사용했고 후보56회만 새로 실행했다. 기존 성적을 다시 얻기 위한 모델 호출, 새 Qwen 호출, 추가 준비 추론, 자동 재시도는 모두0회다.

## 바꾼 문구

기존 영어 공통 지침의 아래 문장 하나를 교체했다.

```text
Do not pass a plan whose executable inputs differ even if requirements.text or source.quote is correct.
```

교체한 문구는 다음과 같다.

```text
Apply this check's specific scope first. Within that scope, do not choose match when executable inputs differ from the original requirement, even if requirements.text or source.quote is correct. If this item is satisfied, choose match regardless of discrepancies assigned to other checks.
```

의도는 개별 검사 지침에 정의된 범위를 먼저 적용하고, 그 범위 안의 실행값 불일치만 해당 검사에서 거절하도록 하는 것이다. 다른 검사가 담당하는 오류는 현재 항목의 판정에 반영하지 않도록 명시했다. 숫자·단위·범위·정렬 등의 담당 검사를 새로 정의하거나 개별 검사 규칙을 바꾸지 않았다.

변경 단위는 기존 문장 하나를 범위/우선순위가 명시된 문구로 교체한 것이다. 새 표현은 길이도 달라 검사당33토큰 늘었다. 단어 하나 또는 길이 하나의 효과만 분리한 실험으로 해석하지 않는다.

## 그대로 둔 것과 비교 경계

- 같은 실제 Qwen 정상5·오류5, 출처·정답표·오류 주입 위치/수치, 원문·이력·확인 문맥·인용문·요구사항·계획·실행 효과·검사 목록·선별 도구/지표 설명·정책을 유지했다. corpus 파일도 바이트가 같다.
- 56개 native 요청의 **state 문자열과 실제 state token prefix가 모두 동일**하다. common 문구를 제외한 검사별 지침·Check location·검사ID·선택지ID/설명/순서·선택지token 그룹·temperature도 같다.
- 수정 대상은 평가 요청의 questions.*.instructions 공통 구절뿐이다. 실행 중 공용 d1_input.py나 서비스 프로필을 바꾸지 않아 기존 모델·메모리 증거·worker를 유지했다.
- 후보 식별자는 비공개manifest의 common-scope-only-v1이다. state를 유지하기 위해 원래 prompt_version 값도 바꾸지 않았고, 실제 후보 문구·변경 패치·입력hash는 별도 보존했다. 이를 제품의 새 지시서 버전으로 표시하지 않는다.
- 고정 계획의 최초 d1 검토만 비교했다. 새 Qwen 생성·Run 도구·웹/API 문항·재계획 복구·최종 답변을 실행하지 않았다. 기존 그래프·최종 JSON/SSE·저장 계약은 유지했다.

## 실제 숫자 오류 검출은 그대로였다

모든 오류 사본의 목표 검사 선택은 전후가 같았다.

| 쌍 | 바꾼 실행값의 종류 | 기존 목표 검사 선택 | 후보 목표 검사 선택 |
|---|---|---|---|
| R01 |압력|value_changed|value_changed|
| R02 |소스 전력|match — 놓침|match — 놓침|
| R03 |바이어스 전력|match — 놓침|match — 놓침|
| R04 |에너지 범위 상한|boundary_changed — 사유 불일치|boundary_changed — 사유 불일치|
| R05 |이온 플럭스 하한 비교값|value_changed|value_changed|

소스 전력 오류의 match 확률은70.65%→73.42%, value_changed는17.05%→19.73%였다. 바이어스 오류는 match60.69%→74.14%, value_changed15.91%→9.77%였다. 범위를 좁힌 공통 문구가 두 숫자 불일치 검출을 개선하지 못했다.

## 줄어든 오판과 새로 생긴 오판

| 검사 종류 | 기존 오판 수 | 후보 오판 수 |
|---|---:|---:|
| 작업 누락 |3|0|
| 필터 누락 |2|0|
| 정렬 |2|1|
| 확인 요청 누락 |**2**|**9**|
| 수치 검사 |3|3|

바이어스 오류 사본 R03.bad의 request.tasks와 request.filter_coverage는 missing→match로 바뀌었다. 실제로 없어진 작업/필터가 없는데 누락이라던 부수 오판은 수정됐다. 압력 오류의 작업/필터 unclear2개, 이온 플럭스 오류의 작업 unclear1개, 범위 오류의 정렬 missing1개도 match로 수정됐다.

반면 request.confirmation_coverage는 원래 맞히던7개 검사를 새로unclear로 바꿨다. 정상4개와 오류3개다. 결과적으로 이 검사가 전체10계획 중9개에서unclear였다. 정상 계획의 단계·입력·확인 요구가 새로 바뀐 것은 없다.

정상 R01/R02/R03의 확인 검사는 후보에서unclear가 각각66.52%/62.56%/57.43%로 가장 높았다. 정상 R05는unclear45.29%, match44.42%로 가까웠다. 정상 R04만 기존과 같이PASS였다. 값이 잘못 직렬화되거나 파서가UNKNOWN을 만들어 낸 것이 아니라 실제 원시 확률에서unclear가 선택됐다.

이전 오답을 정답으로 바꾼 검사는6개, 이전 정답을 오답으로 바꾼 검사는7개다. 나머지 변화1개는 이온 플럭스 오류의 정렬 missing→unclear이며 여전히 오답이다. 따라서56개 중14개 선택이 달라졌고, 전체 정답은44→43으로 낮아졌다.

오류 사본만 보면 부수 오판이9→6으로 줄었지만 정상에서4개가 새로 생겨 전체 부수 오판은9→10이다. 오류의 잘못된PASS가1→0으로 줄어든 것도 수치 오류를 새로 잡았기 때문이 아니다. 소스 전력 오류가 잘못된 확인unclear 때문에PASS→UNCLEAR가 된 것이므로 이를 정확한 검출 개선으로 세지 않는다.

## 환경·비용·메모리

기존 M4 Pro24GiB, LiquidAI/d1-2B의 MLX affine8/group64·일부BF16 보존, Metal GPU, MLX0.32.4·mlx-decision1.3.0, group_size1/independent_batch_size1을 유지했다. 입력은 기존 en-compact-no-view/per_check 상태에 위 공통 구절만 교체했다. 가중치·tokenizer·보정값·라이브러리와 소스 지문을 확인했다.

모델 설정과 실제 LangGraph plan 이전 중단 상태에서 plan_review_enabled=true를 확인했다. Docker VM1536MiB, development 정책을 유지하고 warning/swap은 기록·critical/unknown은 중단 조건으로 삼았다.

- 입력:123,216→125,064토큰, 총1,848토큰·검사당33토큰·**1.50% 증가**. 최대3,189토큰이며 절단0이다.
- GPU동기화 모델score 평균:7.682→7.813초/계획, 관측상**1.70% 증가**. 가중치로드·프로세스시작·count·준비·웹대기는 제외했다. 기준을 재실행하거나 반복/순서를 반전하지 않은 단회 관측이다.
- 후보 OS active+wired+compressor 피크:**17.735GiB**,188표본, warning/critical/unknown0, 추가swap0. 기존swap 자체가0이라는 뜻은 아니다.
- DB OOM0→0이다. 전체OS 피크와 MLX allocator/RSS를 합산하거나 d1 전용 사용량으로 바꾸어 해석하지 않는다.

## 검증과 채택 판단

- 공통 구절 미교체 상태에서 CPU 검사2실패를 확인한 뒤 구현했다. 최종2통과: state 바이트 보존, 공통 한 구절만 교체, 개별 지침·검사 위치·선택지/순서 보존을56개 전체에 대해 확인했다.
- 실제tokenizer 사전 대조는 가중치/forward0회다. state token prefix·선택지token 그룹·보정값이 모두 같았고 문구로 인한33토큰 증가만 확인했다. 실행기4개 파일 py_compile도 통과했다.
- 후보56회가 모두 완료됐고 기존 파서가56개 원시 선택/확률·상태를 그대로 재현했다. 기준 corpus·입력·분석과 모델/소스 지문은 보존했다.
- 평가 동안 기존 model_lease를 보유했고 SIGSTOP·worker 재시작·모델 프로필 변경·다른 앱 종료는 하지 않았다. 종료 후 같은 worker PID40971과 원래 웹/backend/Qwen/d1 PID, d1 해제, 메모리 증거·검토ON·Docker·DB/source/env 보존을 확인했다.
- 사전 기준은 정상5/5 유지, 목표 항목최소3/5·사유최소2/5, 오류 사본 부수 오판9개 미만, 오류PASS 증가 없음, 이전 정답의 새 오판 없음이었다. 정상 통과와 새 오판 방지 조건에 실패했다. **후보 문구는 미채택이며 공용 공통 지침은 원래대로 유지**한다.
- 제품 소스가 바뀌지 않아 전체 제품 테스트나 웹 평가를 추가 실행하지 않았다. 기존 임시gitdir 소실로 Git diff/branch·HEAD/공개파일guard는 확인할 수 없어 내용hash와 문서의 원문/인증값 미포함을 별도로 점검한다. Git 복구·commit·push·배포는 하지 않았다.

원시 입력·확률·비공개 실행기는 Git 제외 `.local/runtime/v2.5-d1-scoped-common/`에 보관한다. 주요 파일은 candidate-common.json, candidate.patch(제품 미적용), scope_common.py/test_scope_common.py, corpus.json/inputs.json, manifest.json, packing-verified.json, evaluation.json, analysis.json, comparison.json, final-runtime-verified.json과 red/green 로그다.

이번 결과는 공통 문구가 검사별 오판 분포에 영향을 준다는 증거다. 그러나 이 문구가 전체 성능을 개선하지는 못했다. 범위 한정이라는 접근 전체가 불가능하다는 결론이나, 소스/바이어스 숫자 오류의 유일한 원인이 공통 문구라는 결론은 내리지 않는다. 확인 검사가unclear를 선택한 내부 이유는 로그에 없으며 추가 대조는 실행하지 않았다.

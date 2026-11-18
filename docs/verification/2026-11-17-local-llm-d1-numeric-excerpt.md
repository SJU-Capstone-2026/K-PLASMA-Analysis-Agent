# d1 숫자 검사 22개 필드 발췌 — 실제 Qwen 계획 전후 비교

2026-11-17, Asia/Seoul.

**핵심:** 숫자 검사에 해당 인자·인용문·실행값만 남기는 발췌기를 구현해 비교했다. 실제 숫자 오류의 항목·사유는 **2/5→5/5**로 개선됐지만, 정상 소스 전력에 새 오판이 생겨 정상 계획 통과는 **5/5→2/5**로 낮아졌다. 숫자 검사 정답도 **19/22→17/22**로 떨어졌다. 숫자 검사 입력은 **21.21%**, 전체 입력은 **7.99%** 줄었고 계획당 모델 score는 관측상 **10.20%** 짧아졌다. **현재 후보는 제품에 채택하지 않았다.**

## 정확도

기준은 [기존 2번+조건부 1·4·5번 구성](2026-11-17-local-llm-d1-conditional-common.md)의 저장된 original 결과다. 미채택된 범위 한정 2번 문구를 사용하지 않았다. 같은 실제 Qwen 정상 5개와 인용문을 보존한 숫자 오류 사본 5개를 사용했다. 새 Qwen 계획을 생성하지 않았다.

| 지표 | 적용 전 | 숫자 필드 발췌 |
|---|---:|---:|
| 정상 계획 최초 PASS |5/5|**2/5**|
| 정상 계획의 잘못된 ISSUE |0/5|**3/5**|
| 실제 오류 항목 검출 |3/5|**5/5**|
| 오류 항목·value_changed 사유 모두 정확 |2/5|**5/5**|
| 오류 계획 전체 ISSUE |4/5|5/5|
| 오류 계획의 잘못된 PASS |1/5|0/5|
| 숫자 검사 정답 |19/22|**17/22**|
| 그대로 둔 검사 정답 |26/34|26/34|
| 전체 검사 정답 |45/56|**43/56**|
| 모든 검사·사유까지 엄격 일치한 계획 |5/10|3/10|

오류 검출 5/5만으로 전체 정확도가 개선됐다고 판단하지 않는다. 정상 입력과 오류 사본 안의 정상인 다른 인자에 대한 새 오판도 포함해야 한다. 발췌한 22개 중 원래 정답이던 5개가 오답으로 바뀌었고, 기존 오답 3개는 정답으로 수정됐다.

### 실제 오류 항목의 변화

| 오류 사본의 변경 종류 | 적용 전 목표 검사 | 발췌 후 목표 검사 |
|---|---|---|
| 압력 숫자 |value_changed|value_changed|
| 소스 전력 숫자 |match — 놓침|**value_changed**|
| 바이어스 전력 숫자 |match — 놓침|**value_changed**|
| 에너지 범위 상한 숫자 |boundary_changed — 사유 불일치|**value_changed**|
| 플럭스 하한 비교값 |value_changed|value_changed|

### 새 오판 5개

| 사례 | 검사 | 적용 전 | 발췌 후 | 정답 |
|---|---|---|---|---|
| R01 정상 |source_power|match|**missing**|match|
| R01 압력 오류 사본의 정상 소스 전력 |source_power|match|**missing**|match|
| R02 정상 |source_power|match|**unexpected**|match|
| R03 정상 |source_power|match|**missing**|match|
| R03 바이어스 오류 사본의 정상 소스 전력 |source_power|match|**missing**|match|

새 오판은 모두 순방향 조회의 source_power 검사에 모였다. 해당 실행값·단위·source.quote는 전후가 같고 발췌 후에도 존재함을 확인했다. 정상 R01은 missing 34.04%, match 33.52%로 가까웠지만, R02는 unexpected 48.97%와 match 14.45%, R03은 missing 43.53%와 match 29.49%였다. 원시 선택지 확률에서 생긴 변화다.

누락 검사 30개와 정렬 검사 4개는 native 요청 및 실제 패킹 토큰이 동일했다. 재실행 결과도 **선택·확률 34개 모두 완전히 같았고 최대 확률 차이는 0**이었다. 기존의 작업·필터 누락 및 정렬 부수 오판 8개는 그대로 남았다.

발췌가 숫자 오류 검출에는 도움이 됐으나 정상 소스 전력 분류를 불안정하게 만든 관측이다. 모델이 왜 missing/unexpected를 선택했는지 내부 이유는 기록되지 않는다. ‘다른 필드를 생략해서 실제 누락으로 해석했다’는 설명이나 특정 필드 이름이 원인이라는 설명을 이번 로그만으로 확정하지 않는다.

## 구현 범위

재사용 가능한 평가용 발췌기를 `agent/python/evals/local_llm_d1_numeric_view.py`에 구현했다. 후보 버전은 literal-numeric-excerpt-1이다. 원본은 전체 PlanDraft 및 기존 check_specs와 대조한 뒤 검토 복사본만 만든다.

- filter 종류 중 고정 리터럴 인자를 검사하는 22개에만 적용했다. 확인·필터·작업 누락 검사 30개와 정렬 검사 4개는 native 요청 전체를 바이트 수준으로 유지했다.
- 숫자 검사에서는 현재 Check location의 입력만 남겼다. 순방향 조회는 해당 pressure/source_power/bias_power 바인딩 하나, 역방향 검색은 해당 지표의 constraint/target_range 행을 남긴다. 같은 지표가 gte/lte로 나뉘면 두 행을 모두 보존한다.
- 실행 숫자·단위·비교 연산자·양쪽 범위 경계·source.message_key·source.quote는 원문 그대로 보존했다. Qwen이 만든 서로 다른 부분 인용을 동일한 질문으로 바꾸지 않았다.
- 전체 사용자 질문·입력 이력·확인 문맥·선별 도구/지표 설명·정책·completed_steps·검토 버전 메타데이터는 유지했다. 코드가 기대 숫자나 정답을 추출해 추가하지 않았다.
- 원래 steps 순서·ID와 선택된 plan_paths를 보존했다. 다른 단계·constraint 행은 발췌 생략 표시로 대체해 배열 위치를 유지한다. 실제 null과 생략 표시는 구분한다.
- 중복 requirements 문구/인용은 id·handled_by 연결만 남겼고, 숫자 검사 복사본의 다른 check_specs 및 중복 program_effects/execution_view를 제외했다. 다른 인자의 숫자가 실행 설명을 통해 다시 유입되지 않도록 했다.
- review_view에 불완전한 검토용 발췌본임과 생략된 필드가 실제 계획의 누락을 뜻하지 않음을 구조화된 속성으로 표시했다. 질문 지침·개별 검사 규칙·선택지 ID/설명/순서·보정값은 변경하지 않았다.
- result_ref/context_ref 또는 선행 단계·guard에 의존하는 숫자, 알 수 없는 구조에는 전체 기준 요청을 보존하는 fallback을 둔다. 이번 22개는 모두 지원되는 고정 리터럴이어서 fallback 없이 발췌됐다. 참조형까지 적용한 결과로 확대 해석하지 않는다.

실제 실행 계획·검토 원본 기록·그래프 노드/간선·도구·JSON/SSE·저장 계약은 변경하지 않았다. 기존 파서는 원본 전체 context로 선택·상태·근거를 재현했다. 이번 발췌기는 평가 경로에 연결했고 공용 worker/서비스의 입력 정책은 변경하지 않았다.

## 토큰과 시간

| 측정 | 적용 전 | 발췌 후 | 관측 감소 |
|---|---:|---:|---:|
| 숫자 검사 22개 총 입력 |45,532|35,874|9,658토큰·21.21%|
| 숫자 검사당 평균 입력 |2,069.64|1,630.64|439토큰|
| 그대로 둔 34개 총 입력 |75,408|75,408|0|
| 전체 56개 총 입력 |120,940|111,282|9,658토큰·7.99%|
| 전체 검사당 평균 입력 |2,159.64|1,987.18|172.46토큰|
| 숫자 검사당 평균 score |1.2922초|0.9841초|23.85%|
| 전체 계획당 평균 score |7.5996초|6.8244초|0.7752초·10.20%|
| 전체 검사당 평균 score |1.3571초|1.2186초|10.20%|

최대 입력은 그대로 둔 검사에서의 3,110토큰이며 절단은 없었다. 시간은 backend.score 호출부터 GPU 동기화 완료까지다. 모델 로드·프로세스 시작·별도 사전 패킹·실행기 대기·웹 처리는 제외했다. 이번 실행기 wall 평균은 계획당 7.618초다.

적용 전은 기존 기록을 재사용했다. 반복·순서 반전 없이 한 번 비교했으며, 동일 입력인 나머지 34개 score도 약 2% 짧아지는 변동이 있었다. 따라서 10.20%를 일반적인 제품 응답 속도 개선율로 단정하지 않는다.

## 환경과 검증

M4 Pro 24GiB, LiquidAI/d1-2B의 MLX affine8/group64·일부 BF16 보존, Metal GPU, MLX 0.32.4·mlx-decision 1.3.0을 유지했다. group_size=1·independent_batch_size=1이다. Docker VM 1536MiB, development 메모리 정책, 기존 준비 증거를 유지했다. 모델 설정과 실제 graph state의 plan_review_enabled=true를 전후 확인했다.

새 d1 의미 검사 56회가 모두 끝났다. 기준 재실행·새 Qwen·warmup·자동 재시도·REPLAN·답변 재작성·Run 도구·추가 웹/API 문항은 0회다. 고정된 10개 계획의 최초 d1 검토만 비교했다.

- CPU 테스트는 구현 전 11실패·3통과를 확인했고, 구현 후 숫자 발췌 14개 및 기존 검토 계약을 합쳐 **29개 통과**했다. 범위 양쪽 경계·paired 경계·target_range·원래 배열 위치·부분 인용·원본 불변·누락 요청 보존·참조/guard fallback을 확인했다.
- 실제 tokenizer 패킹은 가중치 로드·추론 0회다. 22개 입력 모두 작아졌고, 선택지 token 그룹·보정값이 같았다. 나머지 34개 요청·패킹은 기준과 완전히 같았다.
- 56개 원시 결과를 기존 normalize_response/parse_plan_review로 읽어 실제 선택·확률·상태가 일치함을 확인했다. 전체 corpus와 기준 산출물 hash를 보존했다.
- OS active+wired+compressor 피크는 **17.684GiB**, 169표본, warning/critical/unknown 0, 추가 swap 0이었다. OS 전체 관측이며 d1 전용 메모리 개선율로 해석하지 않는다. DB OOM 증가는 없었다.
- model_lease를 유지하며 worker를 종료·일시정지하지 않았다. 종료 후 모델·제품 소스·프로필·worker 환경·프로세스 ID·DB·Docker 한도와 메모리 증거 유효성을 확인했고, d1 서비스는 해제 상태였다.
- 최종 구현으로 frozen 입력 56개를 다시 계산해 일치함을 CPU에서 확인했다. 비교 후 모델을 다시 호출하지 않았다.

검증 명령은 `PYTHONPATH=agent/python:agent/python/src agent/python/.venv/bin/python -m pytest agent/python/tests/v2_local_llm/test_numeric_review_view.py agent/python/tests/v2_local_llm/test_plan_review.py -q`다. 제품 전체 테스트·웹 평가는 실행하지 않았다.

원시 입력·실제 질문/인용·확률·실행기와 manifest는 Git 제외 `.local/runtime/v2.5-d1-numeric-excerpt/`에 보관한다. 핵심 파일은 plan.md, prepare.py, inputs.json, selection.json, manifest.json, packing-verified.json, evaluation.json, analysis.json, comparison.json, production-parser-results.json, completion-verified.json과 red/green/contract 테스트 로그다.

기존 Git 메타데이터 오류로 Git diff/branch 확인은 불가능했다. 제품 소스는 내용 hash로 보존을 확인했고, 공개 문서는 실제 질문·인용문·비밀값 미포함을 별도 검사했다. Git 복구·커밋·push·PR·배포는 하지 않았다.

이번 후보는 오류 검출 개선과 정상 오판 증가가 함께 있어 채택하지 않았다. 후속 변경·추가 모델 대조는 실행하지 않았으며, 수정한 범위 한정 2번 문구도 계속 미반영 상태다.

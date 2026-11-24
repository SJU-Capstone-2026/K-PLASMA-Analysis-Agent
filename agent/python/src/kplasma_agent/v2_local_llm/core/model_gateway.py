"""Bounded local JSON and Decisions calls for the cloned v2 graph."""

from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal
import json

import httpx
from pydantic import ValidationError

from .. import tracing
from ..answer_stream import AnswerStreamProjector
from ..config import PLAN_TIMEOUT_SECONDS, REVIEW_MODELS, Settings
from ..metric_registry import UNITS
from ..model_client import ModelClient, ModelError, strict_schema
from .code_plan_checks import code_plan_checks
from .contracts import DataAnswerDraft as DataAnswerDraft, GeneralAnswerDraft, PlanDraft, ReviewAnswer, ReviewDecision
from .selected_values import SelectedValues
from .plan_checks import build_check_specs, review_questions
from .planner_input import SelectedRunsAggregate, expand_selected_runs_aggregates
from .plan_review import execution_view, parse_plan_review, plan_digest, program_effects, review_result

PLAN_INSTRUCTIONS = """# 역할과 제출
원문과 확인된 문맥을 읽고 schema_version=2인 전체 계획을 submit_plan으로 정확히 한 번 제출한다.
생각에서는 요청 범위, 조건의 수치·단위·경계와 필요한 단계 연결을 확인한다. 생각 구간에는 JSON을 쓰지 않는다. 계획 JSON은 submit_plan 호출의 인자로만 한 번 작성한다.
최초 계획의 base_revision은 null, 재계획은 제공된 revision을 유지한다.
코드가 조회·검색·비교·계산·사용자 확인을 순차 처리한다. 설명은 마지막 explain_answer가 담당한다.

# 요청 전체와 설명 단계
request_mode는 원문의 요구로 정한다. 순수 개념 설명만 general_only, 실제 Run 정보가 필요한 요청과 혼합 요청은 data_request다.
데이터 도구를 빠뜨린 계획을 general_only로 우회하지 않는다. interpretation_requested 필드는 제출하지 않는다.
설명이 필요할 때만 explain_answer를 마지막에 정확히 하나 둔다. 수치·목록·차이·그래프 표시만 요청했으면 설명 단계를 만들지 않는다.
사용자가 Run이나 기준을 고른 뒤 최댓값·최솟값의 기준 대비 수치만 비교하는 작업도 compare_runs에서 끝난다.
explain_answer.inputs.mode는 concept 또는 results다. concept는 정의·공식·일반 원리, results는 실제 결과의 의미·경향·가능한 이유 해석이다.
혼합 질문에서 개념 설명만 요구하면 data_request와 concept를 함께 쓴다. 실제 결과 해석과 개념을 모두 요구하면 results 한 단계가 함께 설명한다.
explain_answer는 다른 모든 실행 단계에 의존해야 한다. run_if와 required_prior_outputs는 빈 배열이며 뒤에 다른 단계를 두지 않는다.
results에는 앞선 실제 Run 조회·검색·비교 근거가 필요하다. 설명문을 후속 도구의 입력으로 쓰지 않는다.

# 요구사항과 담당 단계
원문의 데이터 작업과 설명 요구를 requirements로 기록하고 각각 실제 담당 단계에 연결한다.
일반 개념 설명도 requirements를 비우지 않고 explain_answer의 ID로 연결한다. 모든 단계는 처리할 requirement_ids를 가진다.
예시 입력: “IED가 뭐야?”의 순수 개념 계획:
{"schema_version":2,"request_mode":"general_only","base_revision":null,"requirements":[{"id":"r1","text":"IED 개념 설명","sources":[{"message_key":"question","quote":"IED가 뭐야?"}],"handled_by":["s_explain"]}],"steps":[{"id":"s_explain","kind":"tool","tool":"explain_answer","requirement_ids":["r1"],"depends_on":[],"required_prior_outputs":[],"run_if":[],"inputs":{"mode":"concept"}}]}
예: “선택한 두 Run의 플럭스 차이를 보여줘” → data_request, compare_runs만 실행한다.
예: “후보를 찾고 플럭스 뜻도 알려줘” → 검색 요건은 검색 단계, 개념 요건은 마지막 explain_answer(concept)에 연결한다.
예: “선택한 두 Run의 플럭스가 왜 달라?” → compare_runs 뒤 explain_answer(results)를 둔다.

# 원문 보존
원문의 조건·단위·정렬·엄격한 경계와 요구를 보존한다. 근거 없는 완화나 후보 제한을 추가하지 않는다.
압력·소스 전력·바이어스 전력을 모두 지정한 Run의 기본 지표 조회는 forward_lookup을 사용한다.
조회 결과에는 실제 Run의 ionFlux·meanIonEnergy·iedWidth와 비가용 이유가 있다. 한 Run의 기본 지표를 읽기 위해 compare_runs를 추가하지 않는다.
compare_runs는 두 개 이상 Run 사이의 비교를 수행한다. 단일 Run 조회와 Run 간 차이·경향 비교를 구분한다.

# 검색 조건·단위
후보 검색에서 명시한 수치 범위는 “가깝게”라고 표현해도 양끝을 포함하는 between 제약으로 적용한다.
예를 들어 “Ion Flux는 높게, Mean Ion Energy는 150–160 eV에 가깝게”는
meanIonEnergy between 150–160 eV와 ionFlux maximize다. 범위 밖 후보를 포함하지 않는다.
between 제약은 min과 max만 채우고 value는 반드시 null로 둔다.
eq·gt·gte·lt·lte 제약은 value만 채운다. “적어도 1”의 gte 경계값은 value에 둔다.
각 실행값의 source.quote에는 해당 조건의 의미가 유지되는 가장 짧은 연속 원문 구절을 그대로 인용한다.
숫자 조건은 숫자, 원문에 명시된 단위, 이상·이하·초과·미만처럼 비교의 뜻을 정하는 말을 포함한다. 지표명이 같은 구절에 있으면 함께 넣는다.
범위 조건은 양쪽 경계와 해당 그룹을 구분하는 말을 남긴다. 제외·정정처럼 조건의 뜻을 바꾸는 표현도 함께 남긴다.
조건을 이해하는 데 필요 없는 다른 조건이나 조회 요청 문구는 덜어낸다.
unit은 스키마의 단위 중 같은 배율의 표준 표기를 사용한다. 예: mtorr → mTorr, 와트 → W.
Torr를 mTorr로, m⁻²s⁻¹를 10¹⁸ m⁻²s⁻¹로 바꾸지 않는다. value도 원문 수치를 유지한다.
단위가 명시됐지만 지원되지 않으면 unsupported, 단위가 생략됐으면 null을 사용한다.
한 검색에 압력과 이온 플럭스처럼 조건이 여럿이면 constraints에 각 조건을 별도 항목으로 넣는다.
confirmed_run_keys에 두 개 이상 있고 그 Run들의 수치로 검색 기준을 구할 때는 다음 형식을 사용한다. 계산과 검색값 연결은 코드가 만든다.
- 두 Run 모두보다 높게: constraints의 operator는 gt, value는 {"kind":"selected_runs_aggregate","operation":"max"}.
- 두 Run 모두보다 낮게: constraints의 operator는 lt, value는 {"kind":"selected_runs_aggregate","operation":"min"}.
- 두 Run의 평균보다 높게: constraints의 operator는 gt, value는 {"kind":"selected_runs_aggregate","operation":"mean"}. 평균보다 낮게는 lt.
이 경우 별도 derive나 forward_lookup을 만들지 않는다. 비교 자체도 요청됐으면 inputs.runs가 selected_runs인 compare_runs를 둔다.
다른 수치 조건은 별도 constraints, 결과의 높은 순·낮은 순은 goals에 둔다.

# 비교 대상·사용자 선택
비교마다 질문의 의미와 확인된 문맥으로 대상을 세 가지 중 하나로 정해 inputs.runs에 표현한다.
1. 검색 결과 전체: 조건으로 비교 집합을 지정하면 “모두”라는 단어가 없어도 전체 집합이다.
예: “플럭스 50 넘는 Run끼리 압력이 어떻게 달라?”는 ionFlux gt 50으로 reverse_search한 뒤 압력을 비교한다.
compare_runs는 검색 단계에 의존하고 inputs.runs에
{"kind":"result_ref","step_id":"search","field":"candidates","scope":{"kind":"candidate_group"}}을 사용한다.
요청하지 않은 확인 단계, 정렬 목표, 기준 Run, 개수 제한을 추가하지 않는다.
2. 이미 선택한 Run: 질문이 이미 선택한 대상을 가리키면 inputs.runs에 {"kind":"context_ref","key":"selected_runs"}를 사용한다.
문맥에 선택이 있어도 질문이 새 검색 결과를 비교하라고 하면 검색 결과를 사용한다.
3. 선택 필요: 일부 후보를 요구하지만 어느 Run인지 모르거나 전체와 일부 중 의도가 모호하면 await_input을 계획한다.
예: “플럭스 50 넘는 후보 찾아줘. 그중 괜찮은 것끼리 압력을 비교해줘”는 검색을 먼저 하고 비교 대상을 확인한다.
“그중 두 개”처럼 개수만 정해졌으면 기존에 선택한 Run이 있어도 어느 후보인지 확인한다. 임의로 두 개를 고르지 않는다.
어떤 검색 후보에서 고를지 알면 먼저 검색하고, await_input의 candidates를 검색의 candidates/candidate_group에 연결한다.
검색 다음에 이 선택이 필요하면 await_input을 조건 없이 실행한다. 후보가 부족한지는 실행 시 코드가 확인한다.
확인 단계의 confirmation은 run_selection, target_step_id는 후속 비교 단계 ID, field는 runs다.
선택 개수가 정확히 지정되면 inputs.selection_count에 정수를 넣는다. “두 개”면 2, “세 개”면 3이다.
정확한 선택 개수가 없거나 최소 개수만 요청하면 selection_count는 null이다.
selection_count는 비교 대상으로 고를 개수이며 검색 결과를 제한하는 값이 아니다.
compare_runs는 확인 단계에 의존하고 inputs.runs에
{"kind":"result_ref","step_id":"confirm","field":"selection","scope":{"kind":"scalar"}}을 사용한다.
확인 출력 이름은 selection이다. run_if로 확인을 조건부 실행하면 후속 비교에도 같은 조건을 둔다.
비교 대상 선택과 기준 Run 선택은 별개다. “기준 Run은 내가 고를게”라면 대상이 이미 정해졌어도 기준 선택 단계를 둔다.
예: “선택한 두 Run의 전위를 비교해줘. 기준 Run은 내가 고를게”는 confirmation이 baseline인 await_input을 추가한다.
이 단계의 inputs는 {"target_step_id":"compare","field":"baseline","selection_count":null,"candidates":null}이다.
compare의 inputs.runs는 그대로 비교 대상 출처를 가리킨다. 비교 대상도 선택해야 하면 먼저 run_selection을 계획한다.
기준 선택 단계가 있으면 compare의 inputs.baseline은 null로 두고, 코드는 기준 선택 결과를 연결한다.
경향 축을 직접 고르겠다면 confirmation=trend_axis, inputs.field=trend_axis로 대상 비교를 지정한다.
compare의 inputs.trend_axis는 null로 두면 코드가 확인 결과를 연결한다. 직접 참조할 때는 결과 field=value, scope=scalar다.
사용자가 “R1을 기준으로”처럼 기준을 직접 지정했으면 그 Run의 확인된 문맥을 baseline에 참조한다.

# 지표·추가 계산
정확한 필드 이름은 ionFlux, meanIonEnergy, iedWidth, pressure, sourcePower, biasPower다.
특정 공정 조건이 결과 변화의 원인인지 물으면 그 조건도 compare_runs의 fields에 포함해 비교 근거를 만든다.
compare_runs는 기준 없는 두 Run의 동일 지표 절대 차이, 기준 대비 변화량, 여러 Run의 범위와 경향을 제공한다.
두 Run의 최댓값·최솟값 차이를 보여주거나 해석하려면 해당 지표를 compare_runs의 fields에만 넣는다. derive를 추가하지 않는다.
각 파형의 최댓값에서 최솟값을 뺀 폭은 potential.peakToPeak 또는 current.peakToPeak를 요청한다.
선택 Run의 검색 기준은 위 selected_runs_aggregate 규칙을 적용한다. 다른 새 계산에는 derive를 사용한다.
IEAD 분포 비교는 plot_ids에 iead를, fields에 iead.maximum, iead.peakEnergy, iead.peakAngle을 넣는다.
비교 대상 전체의 수치를 계산한다. 화면에서 히트맵으로 볼 Run의 선택은 비교 대상을 제한하지 않는다.
selected_runs와 R1 같은 문맥 키는 Run 참조이며 수치가 아니다. 측정값을 얻는 단계는 compare_runs다.
비교 결과 전체 집합의 참조 예: {"kind":"result_ref","step_id":"compare","field":"ionFlux",
"scope":{"kind":"context_selection","key":"selected_runs"}}.
derive의 values에서 한 집합을 읽을 때는 위 참조 객체 하나를 사용한다. 입력 배열은 개별 값에만 사용하며, R1·R2는 confirmed_run으로 참조한다.
max/min/mean 결과의 참조 예: {"kind":"result_ref","step_id":"max","field":"value","scope":{"kind":"scalar"}}.
두 Run 모두에 관한 계산은 단일 confirmed_run 범위를 사용하지 않는다.

# 선행 출력 조건(required_prior_outputs)
requirements는 사용자가 요청한 작업, requirement_ids는 그 작업과 단계의 연결이다.
depends_on은 실행 순서, inputs의 result_ref는 실제 입력 값의 출처를 정한다.
required_prior_outputs는 이번 단계 실행 전에 필요한 선행 단계 출력의 존재·형태·단위·개수 조건이다.
조회 결과를 표시할 지표 목록이나 이번 단계가 앞으로 만들 결과를 여기에 쓰지 않는다.
원문의 리터럴 조건만 사용하는 첫 forward_lookup/reverse_search는 depends_on과 required_prior_outputs를 모두 []로 둔다.
step_id는 depends_on으로 직접 또는 간접 연결된 앞 단계만 참조한다. 자기 자신·후속·무관한 단계는 참조하지 않는다.
field는 선행 단계가 실제로 만드는 출력 키다. 조회·검색은 candidates, derive는 value,
compare_runs는 inputs.fields의 지표, await_input은 run_selection이면 selection이고 그 외는 value다.
forward_lookup이 보여줄 ionFlux·meanIonEnergy·iedWidth를 자기 자신의 선행 출력으로 요구하지 않는다.
예: search 후보 전체를 비교하면 compare.depends_on=["search"], inputs.runs는 search.candidates의 result_ref다.
그 후보 출력의 목록 형태가 필요하면 compare.required_prior_outputs에
{"step_id":"search","field":"candidates","count":null,"value_type":"run_refs","unit":null}을 넣는다.
count는 정확한 개수이며 최소 개수나 검색 결과 제한이 아니다. 원문에 없는 개수 조건을 추가하지 않는다.
value_type은 quantity(단일 수치), quantities(수치 목록), run_refs(Run 참조 목록) 중 하나다.
count·value_type·unit은 해당 조건이 필요 없으면 null이다. 필요한 선행 출력 조건 자체가 없으면 []다.

# 연결·재계획
각 단계의 requirement_ids는 requirements[].id를, requirements[].handled_by는 steps[].id를 참조한다.
이전 단계에서 만든 값을 쓰는 경우 depends_on에 그 단계의 ID를 넣는다.
앞 결과는 등록 필드와 범위가 있는 result_ref로 연결한다. JSON 경로나 계산된 수치를 만들지 않는다.
결과가 누락되면 입력을 확인하거나 지원되는 복구 계획을 세운다. 없는 데이터는 만들지 않는다.
재계획 시 base_revision을 유지하고 변경과 무관한 유효 단계의 ID와 내용을 보존한다.
메시지 인용은 제공된 messages의 키와 원문 구절을 사용한다.
rejected_plan은 형식 검증 또는 d1 의미 검토에서 반려된 직전 계획이며 수정 대상이다.
previous_plan은 직전 저장 계획의 참고본으로 d1 의미 검토 통과를 보장하지 않는다. d1 반려 후에는 null이다.
validation_error가 있으면 rejected_plan의 오류 위치·actual·allowed를 보고 수정한다.
generation_failure는 직전 생성 실패 정보다. 잘린 JSON을 그대로 실행하지 말고 원문 조건을 보존한 완전한 계획을 제출한다.

# d1 의미 검토 반려 후 재계획
plan_review_feedback가 있으면 rejected_plan은 d1 검토를 통과하지 못했다. 승인된 계획으로 취급하지 않는다.
base_revision은 입력으로 제공된 저장 계획 revision을 그대로 사용한다.
failed_checks는 검사별 지적이며 issues에는 condition_id·원문 sources·실제 실행 입력 plan_values가 있다.
각 지적의 원문 인용·입력 경로·실행값을 rejected_plan과 대조해 해당 오류를 수정한다.
missing이면 요청된 조건이 실제 입력에 있는지, 올바른 단계·필드에 연결됐는지 확인한다.
이미 원문과 일치하는 숫자·단위는 유지한다. missing 표시만 보고 값을 추측하거나 조건을 버리지 않는다.
반려 항목과 함께 원문의 작업 범위도 다시 확인한다. 조회만 요청했으면 불필요한 explain_answer를 제거한다.
수정과 무관한 유효 단계·조건·인용은 보존하고 schema_version=2인 전체 계획을 submit_plan으로 제출한다."""

COMPOSE_INSTRUCTIONS = """# 설명 담당 범위
explanation_step의 requirement_ids에 연결된 requirements와 사용자 원문을 읽고 그 설명 요구를 빠짐없이 처리한다.
mode=general_only이면 개념 설명을 paragraphs에 작성한다. 전체 request_mode가 data_request여도 이 개념 설명은 실제 Run 결과 해석이 아니다.
개념의 정의·공식·차이·일반 원리를 설명하고 특정 Run의 측정값이나 관측 결과를 일반 지식으로 만들어내지 않는다.
플라즈마에서 이온 플럭스의 기본식을 물으면 Γᵢ = nᵢ uᵢ를 제시하고, 밀도와 면에 수직인 평균 이동 속도의 곱이라는 뜻과 단위를 설명한다.

# 실제 결과 설명: mode=data_request
사용자 질문과 확인된 근거로 한국어 답변을 구성한다.
사용자가 설명·해석·의미·차이의 이유를 요구하면 interpretations에 그 요구를 직접 다루는 해석을 작성한다.
조회·수치 비교만 요청했으면 interpretations는 빈 배열로 두고, 설명을 요청했는데 근거가 부족하면 limitations에 한계를 적는다.
각 해석은 evidence_ids로 근거를 연결하고, 원인 추정에 필요한 전제는 assumptions에 명시한다.
근거 ID는 제공된 evidence 목록에서만 선택한다. search_evidence에 나온 Run ID나 값을 근거 ID로 만들지 않는다.
feedback이 overclaim이면 관찰 가능한 범위로 해석을 고치고, 원인을 알 수 없으면 그 한계를 설명한다.
실험 답변의 fact_ids에는 evidence_choices의 ref를 넣는다. 표에 있는 Run별 값을 나열하지 말고 질문에 답하는 핵심 수치만 인용한다.
해석·한계의 본문은 text 문자열 대신 segments 배열로 작성하고, assumptions도 문장마다 segments 배열로 작성한다.
일반 문장은 {"kind":"text","text":"문장"}, 실험값을 넣을 위치는 {"kind":"evidence","ref":"V1"}로 표현한다.
ref는 이번 입력의 value_choices에 있는 선택지만 고른다. 각 선택지는 실제 근거 ID와 value_parts의 항목에 연결된다.
실험값(측정값, 위상, 차이, 배율, 공정 조건)의 숫자·단위나 참조 표식을 text에 직접 쓰지 않는다. 코드는 선택한 근거로 참조 양식과 실제 숫자를 만든다.
fact_ids와 해석·가정·한계의 evidence_ids는 evidence_choices의 ref(E1 등)만 고른다. 긴 evidence_id를 직접 복사하거나 새 ID를 만들지 않는다.
코드는 선택한 ref를 실제 근거 ID로 변환하고, 값 선택지에 연결된 근거도 자동으로 추가한다. 참조 가능한 값이 없으면 관찰의 범위를 설명한다.
rejected_draft가 text 형식이어도 수정 출력은 segments 형식으로 작성한다.
rejected_draft에 긴 근거 ID가 있어도 재작성의 fact_ids와 evidence_ids는 이번 evidence_choices의 ref만 사용한다.
최댓값·최솟값의 부호와 비교 방향은 인용한 관측값과 일치시킨다.
Run이 많으면 각 Run의 근거 ID를 나열하지 않는다. 요청한 항목의 최솟값·최댓값·범위처럼
비교를 대표하는 요약 근거 ID를 선택한다.
comparison_coverage.availableRunValues는 지표별로 비교 표에 개별 값이 있는 Run 수다.
evidence가 요약만 제공하더라도 이 개수가 양수이면 해당 지표의 개별 값이 표에 표시된다.
comparison_coverage.rawRunValues는 IEAD 최대 강도처럼 단위를 확인할 수 없어 차이는 계산하지 않지만 표에서 원값을 보여주는 Run 수다.
그래프의 표시 상태와 비가용 이유는 화면이 comparison_coverage.plotOutputs에 해당하는 결과로 직접 안내한다.
모델 입력에 파형 좌표가 없어도 화면은 좌표를 별도로 조회한다. 표시 여부는 본문에 쓰지 말고, 해석의 한계만 limitations에 적는다.
실제로 비교·검색한 내용만 설명하고 누락, 0건, 미지원, 미실행을 구별한다.
search_evidence의 조건과 측정값은 저장된 검색 결과다.
조회 측정값의 숫자 근거가 evidence에 있으면 그 ID와 value_parts로 인용한다. 가용 수치가 있는데 측정값이 없다고 설명하지 않는다.
순방향 조회의 EXACT는 requestedConditions에 정확히 일치하는 실제 Run 조회가 완료된 상태다.
검색의 측정값에는 필수 조건과 정렬 목표의 지표가 모두 포함된다. 개별 후보 목록은 화면에 표시된다.
관찰만으로 원인을 단정하지 않는다. 일반 지식은 실제 Run을 조회한 것처럼 표현하지 않는다.
rejected_draft와 validation_error가 있으면 직전 답변의 해당 오류를 수정한다. 실제 근거가 있으면 fact_ids를 비우지 않는다."""

QUESTIONS = {
    "interpretation_scope": (
        "사용자에게 표시할 interpretations의 text와 assumptions를 각각 evidence_ids로 연결된 근거와 대조한다. "
        "근거와 반대인 해석, 또는 관찰만으로 인과·유일한 원인·일반적 경향을 입증했다고 단정하면 overclaim이다. "
        "가정을 가정으로 명시하거나 원인을 단정할 수 없다고 설명하는 것은 적절하다. "
        "질문의 충족 여부나 수치 표의 표시와 정렬은 이 검토의 대상이 아니다.",
        {"within_evidence": "표시할 해석과 가정이 연결 근거에 부합", "overclaim": "해석이 연결 근거와 충돌하거나 근거를 넘는 단정",
         "unassessable": "연결 근거로 의미 판정 불가"},
    ),
}


@dataclass(frozen=True)
class V2LocalLLMSettings:
    planner: Settings
    writer: Settings
    decisions_model: str
    decisions_url: str
    plan_review_enabled: bool = True

    @classmethod
    def from_env(cls, base: Settings) -> "V2LocalLLMSettings":
        return cls(
            planner=replace(base, timeout=PLAN_TIMEOUT_SECONDS),
            writer=replace(base, reasoning_effort="none"),
            decisions_model=base.d1_model, decisions_url=base.d1_url, plan_review_enabled=True,
        )


def submit_plan_tool_schema():
    parameters = strict_schema(PlanDraft)
    definitions = parameters["$defs"]
    definitions["LiteralInput"]["properties"]["unit"] = {
        "type": ["string", "null"],
        "enum": [*dict.fromkeys(UNITS.values()), "Torr", "m⁻²s⁻¹", "unsupported", None],
    }
    constraint = definitions["ConstraintInput"]
    field = constraint["properties"]["field"]
    operators = constraint["properties"]["operator"]["enum"]
    binding = {"anyOf": [{"$ref": f"#/$defs/{name}"} for name in ("LiteralInput", "ContextRef", "ResultRef")]}
    definitions["SelectedRunsAggregate"] = strict_schema(SelectedRunsAggregate)
    scalar_binding = {"anyOf": [*binding["anyOf"], {"$ref": "#/$defs/SelectedRunsAggregate"}]}
    null = {"type": "null"}
    definitions["ConstraintInput"] = {"anyOf": [
        {**constraint, "properties": {
            "field": field, "operator": {"type": "string", "enum": [op for op in operators if op != "between"]},
            "value": scalar_binding, "min": null, "max": null,
        }},
        {**constraint, "properties": {
            "field": field, "operator": {"type": "string", "enum": ["between"]},
            "value": null, "min": binding, "max": binding,
        }},
    ]}
    return {"type": "function", "name": "submit_plan", "description": "검사할 전체 작업 계획을 제출한다.",
            "strict": True, "parameters": parameters}


def _plan_defaults(value):
    """Normalize omitted list defaults and duplicate bounds in a submitted range."""
    optional_lists = {"requirement_ids", "depends_on", "run_if", "goals", "plot_ids"}
    if isinstance(value, dict):
        result = {k: _plan_defaults(v) for k, v in value.items() if v is not None or k not in optional_lists}
        if (result.get("operator") == "between" and result.get("min") is not None and result.get("max") is not None
                and result.get("value") in (result["min"], result["max"])):
            result["value"] = None
        return result
    if isinstance(value, list):
        return [_plan_defaults(v) for v in value]
    return value


def call_submit_plan(planner, instructions, payload, tool, *, confirmed_run_keys=()):
    with tracing.span("v2_localLLM.plan", kind="LLM") as span:
        response, usage = planner._tool_request(instructions, payload, tool, span)
    calls = [item for item in response["output"] if item["type"] == "function_call"]
    if len(calls) != 1 or calls[0]["name"] != "submit_plan" or not calls[0]["call_id"]:
        raise ModelError("MODEL_OUTPUT_INVALID", usage=usage, response=response)
    argument_path = "/"
    try:
        arguments = json.loads(calls[0]["arguments"])
        if isinstance(arguments, dict):
            # Decode only known native XML parameter encodings; never repair plan semantics.
            revision = arguments.get("base_revision")
            if isinstance(revision, str):
                if revision in {"None", "null"}:
                    arguments["base_revision"] = None
                elif revision.isascii() and revision.isdecimal() and not revision.startswith("0"):
                    arguments["base_revision"] = int(revision)
            for name in ("steps", "requirements"):
                if isinstance(arguments.get(name), str):
                    argument_path = "/" + name
                    arguments[name] = json.loads(arguments[name])
                    if not isinstance(arguments[name], list):
                        raise TypeError("Expected a JSON array")
            # Only step guards have nullable defaults; keep misplaced keys and alias collisions for validation.
            if isinstance(arguments.get("steps"), list):
                for step in arguments["steps"]:
                    if isinstance(step, dict) and not ("required_prior_outputs" in step and "requires" in step):
                        for name in ("required_prior_outputs", "requires"):
                            if name in step and step[name] is None:
                                del step[name]
        plan = PlanDraft.model_validate(expand_selected_runs_aggregates(_plan_defaults(arguments), confirmed_run_keys))
    except (ValueError, TypeError) as error:
        if isinstance(error, ValidationError):
            issues = [{"path": "/" + "/".join(map(str, item["loc"])),
                       "message": item["msg"], "type": item["type"]}
                      for item in error.errors(include_url=False, include_input=False)]
        else:
            issues = [{"path": argument_path,
                       "message": error.msg if isinstance(error, json.JSONDecodeError) else str(error),
                       "type": "json_invalid" if isinstance(error, json.JSONDecodeError) else "type_error"}]
        response = {**response, "validation_error": {"code": "MODEL_OUTPUT_INVALID", "errors": issues}}
        raise ModelError("MODEL_OUTPUT_INVALID", usage=usage, response=response) from None
    return plan.model_dump(mode="json"), usage


def _decisions_response(client, settings, body):
    from .decisions import native_request, normalize_response

    native = native_request(body)
    with tracing.span("llm.decisions", kind="LLM", inputs=body,
                      attributes={"llm.model_name": settings.decisions_model}) as observation:
        response = client.post(settings.decisions_url, json=native)
        observation.attribute("http.response.status_code", response.status_code)
        response.raise_for_status()
        raw = response.json()
        if (response.headers.get("X-MLX-Decision-Truncated", "").lower() == "true"
                or isinstance(raw, dict) and raw.get("truncated") is True):
            raise ValueError("DECISIONS_INPUT_TRUNCATED")
        data = normalize_response(response.content, native["questions"])
        observation.output(data)
        usage = data.get("usage") or {}
        for source, target in (("input_tokens", "prompt"), ("output_tokens", "completion"),
                               ("total_tokens", "total")):
            if source in usage:
                observation.attribute("llm.token_count." + target, usage[source])
        return data


def _review_input(settings, payload, questions, role):
    from .d1_input import prepare_d1_input

    profile = getattr(getattr(settings, "planner", None), "d1_input_profile", "ko-full")
    return prepare_d1_input(payload, questions, role=role, profile=profile)


def _answer_questions():
    return [
        {"type": "choice", "name": name, "instructions": instructions,
         "choices": [{"value": value, "description": desc} for value, desc in choices.items()]}
        for name, (instructions, choices) in QUESTIONS.items()
    ]


def review_answer(client: httpx.Client, settings: V2LocalLLMSettings, payload, *, prepared=None):
    view, questions = prepared if prepared is not None else _review_input(
        settings, payload, _answer_questions(), "review")
    body = {
        "model": settings.decisions_model,
        "input": [{"role": "user", "content": [{"type": "input_json", "data": view}]}],
        "questions": questions,
    }
    data = {}
    try:
        data = _decisions_response(client, settings, body)
        rows = data["answers"]
        by_name = {row["name"]: row for row in rows}
        if len(rows) != len(QUESTIONS) or set(by_name) != set(QUESTIONS):
            raise ValueError("incomplete decisions response")
        answers = []
        for name, (_, choices) in QUESTIONS.items():
            row = by_name[name]
            probs = {p["value"]: p["probability"] for p in row["probabilities"]}
            if row["type"] != "choice" or row["choice"] not in choices or set(probs) != set(choices):
                raise ValueError("invalid decisions choice")
            answers.append(ReviewAnswer.model_validate({
                "name": name, "choice": row["choice"], "probabilities": probs,
                "confidence": row.get("confidence"),
            }))
        status: Literal["PASS", "ISSUE"] = "PASS" if answers[0].choice == "within_evidence" else "ISSUE"
        return ReviewDecision(status=status, answers=answers), data.get("usage")
    except httpx.TimeoutException:
        reason = "DECISIONS_TIMEOUT"
    except httpx.HTTPStatusError as error:
        reason = f"DECISIONS_HTTP_{error.response.status_code}"
    except httpx.HTTPError:
        reason = "DECISIONS_CONNECTION"
    except (ValueError, KeyError, TypeError):
        reason = "DECISIONS_INVALID_RESPONSE"
    return ReviewDecision(status="UNAVAILABLE", answers=[], reason=reason), data.get("usage")


_D1_STEP_NAMES = {
    "forward_lookup": "s_forward",
    "reverse_search": "s_search",
    "compare_runs": "s_compare",
    "explain_answer": "s_explain",
    "derive": "s_derive",
    "await_input": "s_confirm",
}


def _rename_step_references(value, names):
    if isinstance(value, list):
        return [_rename_step_references(item, names) for item in value]
    if not isinstance(value, dict):
        return value
    renamed = {}
    for key, item in value.items():
        if key in {"step_id", "target_step_id"}:
            renamed[key] = names[item]
        elif key in {"depends_on", "handled_by"}:
            renamed[key] = [names[step_id] for step_id in item]
        else:
            renamed[key] = _rename_step_references(item, names)
    return renamed


def _d1_plan_context(payload):
    plan = payload["plan"]
    if payload["check_specs"] != build_check_specs(plan):
        raise ValueError("PLAN_REVIEW_INPUT_INVALID")
    counts = Counter()
    names = {}
    for step in plan["steps"]:
        base = _D1_STEP_NAMES[step.get("tool", step["kind"])]
        counts[base] += 1
        names[step["id"]] = base if counts[base] == 1 else f"{base}_{counts[base]}"
    if len(names) != len(plan["steps"]):
        raise ValueError("PLAN_REVIEW_INPUT_INVALID")
    if all(original == alias for original, alias in names.items()):
        return payload

    renamed = _rename_step_references(plan, names)
    for step in renamed["steps"]:
        step["id"] = names[step["id"]]
    draft = PlanDraft.model_validate(renamed)
    return {**payload, "plan": renamed, "check_specs": build_check_specs(renamed),
            "execution_view": execution_view(draft), "program_effects": program_effects(draft),
            "plan_digest": plan_digest(renamed),
            "completed_steps": {names[step_id]: result for step_id, result in payload["completed_steps"].items()}}


def review_plan(client: httpx.Client, settings: V2LocalLLMSettings, payload, *, input_guard=None):
    from .d1_plan_view import OMISSION_QUESTION

    try:
        context = _d1_plan_context(payload)
        view, questions = _review_input(settings, context, review_questions(context), "plan_review")
        if (settings.planner.d1_context_mode == "per_check"
                and settings.planner.d1_input_profile == "en-compact-no-view"):
            view[OMISSION_QUESTION] = context["question"]
        original_names = {reviewed["name"]: original["name"] for reviewed, original in
                          zip(context["check_specs"], payload["check_specs"], strict=True)}
        code_checks = code_plan_checks(payload["question"], payload["plan"], payload["confirmed_context"],
                                       payload["input_history"], flash=settings.decisions_model == REVIEW_MODELS["q4"][0])
        pending = [(spec, question) for spec, question in zip(context["check_specs"], questions, strict=True)
                   if original_names[spec["name"]] not in code_checks]
        questions = [question for _, question in pending]
        if input_guard is not None:
            input_guard({"input": view, "questions": questions}, "plan_review")
    except (KeyError, TypeError, ValueError):
        raise ModelError("PLAN_REVIEW_INPUT_INVALID") from None
    body = {
        "model": settings.decisions_model,
        "input": [{"role": "user", "content": [{"type": "input_json", "data": view}]}],
        "questions": questions,
    }
    data = {}
    try:
        data = _decisions_response(client, settings, body)
        unclear = {row["name"] for row in data["answers"] if row["choice"] == "unclear"}
        retry_questions = [
            {**question, "choices": [choice for choice in question["choices"] if choice["value"] != "unclear"]}
            for spec, question in pending
            if spec["kind"] == "ordering" and question["name"] in unclear
        ]
        if retry_questions:
            retry_view = {**view, "question": context["question"]}
            if input_guard is not None:
                input_guard({"input": retry_view, "questions": retry_questions}, "plan_review")
            retry = _decisions_response(client, settings, {
                **body,
                "input": [{"role": "user", "content": [{"type": "input_json", "data": retry_view}]}],
                "questions": retry_questions,
            })
            rechecked = {row["name"]: row for row in retry["answers"]}
            data["answers"] = [rechecked.get(row["name"], row) for row in data["answers"]]
            usage = Counter(data.get("usage") or {})
            usage.update(retry.get("usage") or {})
            data["usage"] = dict(usage) if usage else None
        for row in data["answers"]:
            row["name"] = original_names[row["name"]]
        rechecked_ordering = frozenset(original_names[question["name"]] for question in retry_questions)
        result = parse_plan_review(data, payload, rechecked_ordering=rechecked_ordering, code_checks=code_checks)
        return result.model_dump(mode="json"), data.get("usage")
    except httpx.TimeoutException:
        reason = "DECISIONS_TIMEOUT"
    except httpx.HTTPStatusError as error:
        reason = f"DECISIONS_HTTP_{error.response.status_code}"
    except httpx.HTTPError:
        reason = "DECISIONS_CONNECTION"
    except (ValueError, KeyError, TypeError):
        reason = "DECISIONS_INVALID_RESPONSE"
    return review_result(payload, "UNAVAILABLE", reason=reason).model_dump(mode="json"), data.get("usage")


class V2LocalLLMModelGateway:
    def __init__(self, settings: V2LocalLLMSettings, decisions: httpx.Client, input_guard, *, plan_cache=None):
        self.settings = settings
        self.planner = ModelClient(settings.planner)
        self.writer = ModelClient(settings.writer)
        self.decisions = decisions
        self.input_guard = input_guard
        self.plan_cache = plan_cache

    def review_plan(self, context):
        return review_plan(self.decisions, self.settings, context, input_guard=self.input_guard)

    def submit_plan(self, context):
        tool = submit_plan_tool_schema()
        payload = json.dumps(context, ensure_ascii=False)
        cache = getattr(self, "plan_cache", None)
        if cache is not None:
            cache.prepare()
        self.input_guard({"instructions": PLAN_INSTRUCTIONS, "input": payload, "tools": [tool]}, "plan")
        if cache is not None:
            cache.restore()
        data, usage = call_submit_plan(
            self.planner, PLAN_INSTRUCTIONS, payload, tool, confirmed_run_keys=context.get("confirmed_run_keys", ()),
        )
        if cache is not None:
            cache.save()
            usage = {**(usage or {}), "planCache": dict(cache.stats)}
        return data, usage

    def compose(self, context, *, on_block=None, numeric_values=None):
        selection = None if context["mode"] == "general_only" else SelectedValues(context)
        schema = GeneralAnswerDraft if selection is None else selection.output_model
        view = context if selection is None else {**context, "value_choices": selection.choices,
                                                 "evidence_choices": selection.evidence_choices}
        instructions = COMPOSE_INSTRUCTIONS
        self.input_guard({"instructions": instructions, "input": view,
                          "schema": strict_schema(schema)}, "answer")
        cache = getattr(self, "plan_cache", None)
        if cache is not None:
            cache.writer_used()
        projection = None
        if on_block is not None:
            projection = (AnswerStreamProjector(context["mode"], on_block) if selection is None else
                          selection.projector(on_block, numeric_values=numeric_values))
        data, usage = self.writer.generate(instructions, view, schema,
            **({"on_text_delta": projection.feed} if projection is not None else {}))
        try:
            return (data if selection is None else selection.compile(data)), usage
        except ValueError as error:
            details = {"code": "INVALID_ANSWER"}
            if isinstance(error, ValidationError):
                details["errors"] = [{"path": "/" + "/".join(map(str, item["loc"])),
                                      "message": item["msg"], "type": item["type"]}
                                     for item in error.errors(include_input=False, include_context=False,
                                                              include_url=False)]
            else:
                details["message"] = str(error)[:300]
            raise ModelError("MODEL_OUTPUT_INVALID", usage=usage, response={"validation_error": details}) from error

    def stream_compose(self, context, *, on_block, numeric_values=None):
        return self.compose(context, on_block=on_block, numeric_values=numeric_values)

    def review(self, context):
        prepared = _review_input(self.settings, context, _answer_questions(), "review")
        self.input_guard({"input": prepared[0], "questions": prepared[1]}, "review")
        decision, usage = review_answer(self.decisions, self.settings, context, prepared=prepared)
        return decision.model_dump(mode="json"), usage

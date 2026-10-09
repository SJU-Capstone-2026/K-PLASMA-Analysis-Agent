from .explanation_cases import EXPLANATION_CASES
from kplasma_agent.answer_contracts import ComparisonResultV2


def test_forty_question_packets_have_raw_questions_and_code_comparison_evidence():
    assert len(EXPLANATION_CASES) == 40
    assert all(case.question for case in EXPLANATION_CASES)
    comparisons = [case for case in EXPLANATION_CASES if case.kind == "compare_runs"]
    assert len(comparisons) == 20
    for case in comparisons:
        result = ComparisonResultV2.model_validate(case.evidence)
        assert len(result.runs) == 2 and result.observations
    assert all(case.evidence == {} for case in EXPLANATION_CASES if case.kind == "generate_answer")

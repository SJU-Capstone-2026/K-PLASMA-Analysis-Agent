from copy import deepcopy

import pytest

from agent.python.evals.plan_review_cases import cases
from kplasma_agent.v2.plan_review import build_plan_review_context, parse_plan_review, plan_review_feedback


def context(case_id='P01', bad=False):
    from kplasma_agent.v2.plan_validation import validate_plan
    case = next(c for c in cases() if c.id == case_id)
    plan = validate_plan(case.bad if bad else case.good, messages={'question': case.question},
                         context_keys=set(case.context), selected_run_keys={'R1', 'R2'})
    return build_plan_review_context(plan, 1, case.question, [], case.context, {})


def reply(payload, failure=None, choice='value_changed'):
    from kplasma_agent.v2.plan_checks import review_questions
    return {'answers': [
        {'type': 'choice', 'name': q['name'], 'choice': choice if q['name'] == failure else 'match',
         'probabilities': [{'value': c['value'], 'probability': float(c['value'] == 'match')}
                           for c in q['choices']], 'confidence': 0.01}
        for q in review_questions(payload)
    ]}


def test_checks_separate_filter_sort_and_operation_without_reparsing_question():
    payload = context()
    specs = {s['name']: s for s in payload['check_specs']}
    assert {'filter.search.ionFlux', 'filter.search.meanIonEnergy', 'ordering.search',
            'operation.threshold', 'targets.compare', 'request.filter_coverage'} <= set(specs)
    assert specs['filter.search.meanIonEnergy']['paths'] == [['steps', 2, 'inputs', 'constraints', 1]]
    assert specs['ordering.search']['paths'] == [['steps', 2, 'inputs', 'goals']]
    assert context('P04', True)['check_specs'][1]['name'] == 'request.filter_coverage'


def test_rejection_evidence_comes_from_saved_original_and_actual_plan_not_model_text():
    payload = context(bad=True)
    result = parse_plan_review(reply(payload, 'filter.search.meanIonEnergy'), payload)
    assert result.status == 'ISSUE'
    failed = next(c for c in result.checks if c.name == 'filter.search.meanIonEnergy')
    assert failed.choice == 'value_changed'
    assert failed.issue['sources'][0]['quote'] == payload['question']
    actual, = failed.issue['plan_values']
    assert actual['path'] == '/steps/2/inputs/constraints/1'
    assert actual['value']['operator'] == 'gt' and actual['value']['value']['value'] == 0
    feedback = plan_review_feedback(result)
    assert feedback['issues'][0]['condition_id'] == 'filter.search.meanIonEnergy'
    assert feedback['issues'][0]['issue_type'] == 'value_changed'
    assert feedback['issues'][0]['plan_values'] == failed.issue['plan_values']
    assert result.checks[0].issue is None


@pytest.mark.parametrize('case_id,check_id', [('P11', 'baseline.compare'), ('P13', 'selection_count.choose')])
def test_future_baseline_and_exact_selection_are_independent_conditions(case_id, check_id):
    payload = context(case_id)
    assert check_id in {s['name'] for s in payload['check_specs']}
    result = parse_plan_review(reply(payload), payload)
    assert result.status == 'PASS'
    if case_id == 'P13':
        bad = context(case_id, True)
        result = parse_plan_review(reply(bad, check_id), bad)
        issue = next(c.issue for c in result.checks if c.name == check_id)
        assert issue['plan_values'][0]['value'] == 3


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'unknown', 'wrong_reason'])
def test_partial_or_unregistered_condition_answers_cannot_approve(corruption):
    payload = context()
    data = reply(payload)
    if corruption == 'missing':
        data['answers'].pop()
    elif corruption == 'duplicate':
        data['answers'][-1] = deepcopy(data['answers'][0])
    elif corruption == 'unknown':
        data['answers'][-1]['name'] = 'model_invented_condition'
    else:
        data['answers'][0]['choice'] = 'unit_changed'  # Task coverage cannot report a unit error.
    with pytest.raises(ValueError):
        parse_plan_review(data, payload)


def test_old_three_check_pass_cannot_approve_a_new_condition_review():
    old = [{'name': name, 'type': 'choice', 'choice': 'match', 'probabilities': []}
           for name in ('request_coverage', 'condition_preservation', 'target_operation_alignment')]
    with pytest.raises(ValueError):
        parse_plan_review({'answers': old}, context())


def test_gateway_sends_all_condition_questions_once_with_rejection_evidence():
    import json
    import httpx
    from kplasma_agent.config import Settings
    from kplasma_agent.v2.model_gateway import V2ModelGateway, V2Settings

    payload = context(bad=True)
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        assert {q['name'] for q in body['questions']} == {s['name'] for s in payload['check_specs']}
        assert body['input'][0]['content'][0]['data'] == payload
        return httpx.Response(200, json=reply(payload, 'filter.search.meanIonEnergy'))

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        gateway = V2ModelGateway(V2Settings.from_env(Settings()), client, lambda *_: None)
        result, _ = gateway.review_plan(payload)
    assert len(calls) == 1
    assert result['status'] == 'ISSUE'
    assert next(c for c in result['checks'] if c['issue'])['issue']['plan_values'][0]['value']['value']['value'] == 0


def test_unknown_saved_condition_kind_is_validation_failure_not_unhandled_keyerror():
    from kplasma_agent.v2.plan_review import PlanReviewResult
    payload = context()
    saved = parse_plan_review(reply(payload), payload).model_dump(mode='json')
    saved['checks'][0]['kind'] = 'unknown_future_kind'
    with pytest.raises(ValueError):
        PlanReviewResult.model_validate(saved)


def test_legacy_review_record_can_be_read_but_cannot_approve_new_context():
    from kplasma_agent.v2.plan_review import PlanReviewResult, matches_review_context
    payload = context()
    saved = {'schema_version': 1, 'status': 'PASS',
             **{k: payload[k] for k in ('plan_revision', 'plan_digest', 'input_digest', 'prompt_version')},
             'checks': [{'name': name, 'choice': 'match', 'probabilities': {'match': 1, 'mismatch': 0, 'unclear': 0},
                         'confidence': 1} for name in ('request_coverage', 'condition_preservation', 'target_operation_alignment')]}
    legacy = PlanReviewResult.model_validate(saved)
    assert legacy.status == 'PASS'
    assert not matches_review_context(legacy, payload)


def test_trend_axis_and_conditional_execution_are_reviewed_as_distinct_conditions():
    from kplasma_agent.v2.contracts import PlanDraft
    from kplasma_agent.v2.plan_review import build_plan_review_context
    case = next(c for c in cases() if c.id == 'P01')
    raw = case.good.model_dump(mode='json')
    raw['steps'][0]['inputs']['trend_axis'] = {
        'kind': 'literal', 'value': 'sourcePower', 'unit': None,
        'source': {'message_key': 'question', 'quote': case.question},
    }
    payload = build_plan_review_context(PlanDraft.model_validate(raw), 1, case.question, [], case.context, {})
    specs = {s['name']: s for s in payload['check_specs']}
    assert specs['trend_axis.compare']['paths'] == [['steps', 0, 'inputs', 'trend_axis']]
    assert specs['execution_guards.threshold']['paths'] == [['steps', 1, 'run_if'], ['steps', 1, 'requires']]
    result = parse_plan_review(reply(payload, 'trend_axis.compare', 'direction_changed'), payload)
    failed = next(c.issue for c in result.checks if c.issue)
    assert failed['plan_values'][0]['value']['value'] == 'sourcePower'


def test_baseline_selection_has_one_semantic_owner_after_code_validates_its_connection():
    payload = context('P13')
    names = {s['name'] for s in payload['check_specs']}
    assert 'baseline.compare' in names
    assert 'selection_targets.choose' in names
    assert 'selection_targets.baseline' not in names

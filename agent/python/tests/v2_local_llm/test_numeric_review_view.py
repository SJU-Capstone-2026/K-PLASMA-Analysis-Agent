"""Synthetic plan excerpts; no model calls or real Run data."""
from copy import deepcopy
import json

import pytest

from evals.local_llm_d1_numeric_view import project_numeric_review
from kplasma_agent.v2_local_llm.core.contracts import PlanDraft
from kplasma_agent.v2_local_llm.core.decisions import native_request
from kplasma_agent.v2_local_llm.core.plan_checks import review_questions
from kplasma_agent.v2_local_llm.core.plan_review import build_plan_review_context


def literal(value, unit, quote):
    return {'kind': 'literal', 'value': value, 'unit': unit,
            'source': {'message_key': 'question', 'quote': quote}}


def request(steps, check):
    question = 'synthetic question: pressure 2, source 30, bias 40, energy 11 through 13'
    plan = PlanDraft.model_validate({'schema_version': 2, 'request_mode': 'data_request', 'base_revision': None,
        'requirements': [{'id': 'r', 'text': question, 'sources': [{'message_key': 'question', 'quote': question}],
                          'handled_by': [s['id'] for s in steps]}],
        'steps': [{**s, 'requirement_ids': ['r']} for s in steps]})
    context = build_plan_review_context(plan, 1, question, [], {}, {})
    questions = [q for q in review_questions(context) if q['name'] == check]
    assert len(questions) == 1
    return native_request({'input': [{'role': 'user', 'content': [{'type': 'input_json', 'data': context}]}],
                           'questions': questions})


def forward():
    return {'id': 'lookup', 'kind': 'tool', 'tool': 'forward_lookup',
            'inputs': {'pressure': literal(2, 'mTorr', 'pressure 2'),
                       'source_power': literal(30, 'W', 'source 30'),
                       'bias_power': literal(41, 'W', 'bias 40')}}


def at(value, path):
    for part in path:
        value = value[part]
    return value


def test_numeric_excerpt_preserves_the_mismatch_and_quote_without_other_execution_values():
    native = request([forward()], 'filter.lookup.bias_power')
    before = deepcopy(native)
    projected, trace = project_numeric_review(native)
    state = json.loads(projected['state'])
    original = json.loads(native['state'])
    assert set(state['plan']['steps'][0]['inputs']) == {'bias_power'}
    assert state['plan']['steps'][0]['inputs']['bias_power'] == original['plan']['steps'][0]['inputs']['bias_power']
    assert state['plan']['steps'][0]['inputs']['bias_power']['value'] == 41
    assert state['plan']['steps'][0]['inputs']['bias_power']['source']['quote'] == 'bias 40'
    assert 'program_effects' not in state and 'execution_view' not in state
    assert len(state['check_specs']) == 1
    assert state['question'] == original['question']
    assert projected['questions'] == native['questions']
    assert state['review_view']['complete_executable_plan'] is False
    assert state['review_view']['omitted_fields_are_not_missing_plan_fields'] is True
    assert native == before and trace['action'] == 'selected'


@pytest.mark.parametrize('check', ['request.tasks', 'request.filter_coverage', 'request.confirmation_coverage'])
def test_omission_requests_remain_byte_identical(check):
    native = request([forward()], check)
    projected, trace = project_numeric_review(native)
    assert projected == native
    assert trace['action'] == 'unchanged'


@pytest.mark.parametrize('mode', ['between', 'paired', 'target_range'])
def test_both_range_boundaries_and_original_array_indexes_are_preserved(mode):
    bounds = {'field': 'meanIonEnergy', 'min': literal(11, 'eV', 'energy 11'),
              'max': literal(14, 'eV', 'through 13')}
    other = {'field': 'pressure', 'operator': 'eq', 'value': literal(2, 'mTorr', 'pressure 2')}
    if mode == 'paired':
        rows = [{'field': 'meanIonEnergy', 'operator': 'gte', 'value': bounds['min']},
                {'field': 'meanIonEnergy', 'operator': 'lte', 'value': bounds['max']}]
    else:
        rows = [{**bounds, **({'direction': 'target_range'} if mode == 'target_range' else {'operator': 'between'})}]
    inputs = {'constraints': [other, *rows] if mode != 'target_range' else [other],
              'goals': rows if mode == 'target_range' else []}
    native = request([{'id': 'search', 'kind': 'tool', 'tool': 'reverse_search', 'inputs': inputs}],
                     'filter.search.meanIonEnergy')
    projected, trace = project_numeric_review(native)
    state, original = json.loads(projected['state']), json.loads(native['state'])
    assert len(state['check_specs']) == 1
    spec = state['check_specs'][0]
    for path in spec['paths']:
        assert at(state['plan'], path) == at(original['plan'], path)
    assert state['plan']['steps'][0]['inputs']['constraints'][0] == {'omitted_from_review': True}
    assert trace['action'] == 'selected'


@pytest.mark.parametrize('feature', ['result_ref', 'context_ref', 'depends_on', 'run_if', 'required_prior_outputs'])
def test_referenced_or_dependent_numbers_keep_the_complete_request(feature):
    step = forward()
    if feature == 'result_ref':
        step['inputs']['bias_power'] = {'kind': 'result_ref', 'step_id': 'prior', 'field': 'value', 'scope': {'kind': 'scalar'}}
    elif feature == 'context_ref':
        step['inputs']['bias_power'] = {'kind': 'context_ref', 'key': 'selected_runs'}
    elif feature == 'depends_on':
        step[feature] = ['prior']
    elif feature == 'run_if':
        step[feature] = [{'step_id': 'prior', 'field': 'candidate_count', 'operator': 'gte', 'value': 1}]
    else:
        step[feature] = [{'step_id': 'prior', 'field': 'value'}]
    native = request([step], 'filter.lookup.bias_power')
    projected, trace = project_numeric_review(native)
    assert projected == native
    assert trace['action'] == 'fallback'


def test_unknown_or_corrupted_check_does_not_guess_a_field():
    native = request([forward()], 'filter.lookup.bias_power')
    state = json.loads(native['state'])
    state['check_specs'][-1]['paths'] = [['steps', 0, 'inputs', 'source_power']]
    native['state'] = json.dumps(state)
    projected, trace = project_numeric_review(native)
    assert projected == native
    assert trace['action'] == 'fallback'


def test_unrelated_steps_keep_indexes_without_their_executable_inputs():
    unrelated = {'id': 'explain', 'kind': 'tool', 'tool': 'explain_answer', 'inputs': {'mode': 'concept'}}
    native = request([unrelated, forward()], 'filter.lookup.bias_power')
    projected, trace = project_numeric_review(native)
    state = json.loads(projected['state'])
    assert [s['id'] for s in state['plan']['steps']] == ['explain', 'lookup']
    assert state['plan']['steps'][0]['omitted_from_review'] is True
    assert 'inputs' not in state['plan']['steps'][0]
    assert state['plan']['steps'][1]['inputs']['bias_power']['value'] == 41
    assert trace['action'] == 'selected'

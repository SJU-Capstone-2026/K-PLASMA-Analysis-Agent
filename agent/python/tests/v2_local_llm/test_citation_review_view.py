"""Quote naming at the d1 review boundary; no real model or data."""
from copy import deepcopy
import json

import pytest

from evals.local_llm_d1_citation_view import rename_numeric_citations
from evals.local_llm_d1_numeric_view import project_numeric_review
from .test_numeric_review_view import forward, request


def excerpt(check='filter.lookup.source_power'):
    native, trace = project_numeric_review(request([forward()], check))
    assert trace['action'] == 'selected'
    native['questions'][check]['instructions'] += ' Even if source.quote is correct, compare the executable input.'
    state = json.loads(native['state'])
    state['tool_contracts']['bindings']['literal'] = 'Original number, unit and source.quote.'
    native['state'] = json.dumps(state)
    return native


def test_renaming_preserves_power_parameter_quote_value_and_original_request():
    native = excerpt()
    before = deepcopy(native)
    renamed, trace = rename_numeric_citations(native)
    original = json.loads(native['state'])
    state = json.loads(renamed['state'])
    old = original['plan']['steps'][0]['inputs']['source_power']
    new = state['plan']['steps'][0]['inputs']['source_power']
    assert 'source' not in new
    assert new['citation'] == old['source']
    assert {k:v for k,v in new.items() if k != 'citation'} == {k:v for k,v in old.items() if k != 'source'}
    assert state['check_specs'] == original['check_specs']
    assert 'source.quote' not in renamed['questions']['filter.lookup.source_power']['instructions']
    assert 'citation.quote' in renamed['questions']['filter.lookup.source_power']['instructions']
    assert state['tool_contracts']['bindings']['literal'] == 'Original number, unit and citation.quote.'
    for key in ['question','input_history','confirmed_context','policy_context','review_view']:
        assert state[key] == original[key]
    assert native == before and trace['renamed_citations'] == 1


def test_user_text_that_mentions_source_quote_is_never_rewritten():
    native = excerpt()
    state = json.loads(native['state'])
    state['question'] = 'User text mentions source.quote verbatim.'
    state['input_history'] = [{'text': 'Keep source.quote exactly.'}]
    state['plan']['steps'][0]['inputs']['source_power']['source']['quote'] = 'source.quote verbatim'
    native['state'] = json.dumps(state)
    renamed, _ = rename_numeric_citations(native)
    view = json.loads(renamed['state'])
    assert view['question'] == state['question']
    assert view['input_history'] == state['input_history']
    assert view['plan']['steps'][0]['inputs']['source_power']['citation']['quote'] == 'source.quote verbatim'


@pytest.mark.parametrize('check', ['request.filter_coverage', 'request.confirmation_coverage'])
def test_non_excerpt_checks_remain_byte_identical(check):
    native = request([forward()], check)
    renamed, trace = rename_numeric_citations(native)
    assert renamed == native
    assert trace['action'] == 'unchanged'


def test_both_range_boundary_citations_are_renamed():
    from .test_numeric_review_view import literal
    step = {'id':'search','kind':'tool','tool':'reverse_search','inputs':{
        'constraints':[{'field':'meanIonEnergy','operator':'between',
                        'min':literal(11,'eV','energy 11'), 'max':literal(14,'eV','through 13')}], 'goals':[]}}
    native, _ = project_numeric_review(request([step],'filter.search.meanIonEnergy'))
    renamed, trace = rename_numeric_citations(native)
    a=json.loads(native['state'])['plan']['steps'][0]['inputs']['constraints'][0]
    b=json.loads(renamed['state'])['plan']['steps'][0]['inputs']['constraints'][0]
    assert trace['renamed_citations'] == 2
    for boundary in ['min','max']:
        assert b[boundary]['citation'] == a[boundary]['source']
        assert b[boundary]['value'] == a[boundary]['value']


def test_conflicting_citation_key_is_rejected_without_overwriting():
    native = excerpt()
    state=json.loads(native['state'])
    state['plan']['steps'][0]['inputs']['source_power']['citation']={'message_key':'question','quote':'different'}
    native['state']=json.dumps(state)
    before=deepcopy(native)
    with pytest.raises(ValueError, match='citation'):
        rename_numeric_citations(native)
    assert native == before

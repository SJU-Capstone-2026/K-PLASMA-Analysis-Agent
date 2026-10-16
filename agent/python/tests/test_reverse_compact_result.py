from copy import deepcopy
from kplasma_agent.domain.reverse import search_reverse
from kplasma_agent.domain.validation import validate_result


def run(index, energy, flux):
    return {'runId': f'TEST-{index}', 'runVersionId': str(index), 'pressure': 8, 'sourcePower': 300, 'biasPower': 600,
            'metrics': {'meanIonEnergy': energy, 'ionFlux': flux, 'iedWidth': 10},
            'qualityStatus': 'VERIFIED', 'catalogStatus': 'READY', 'convergenceStatus': 'CONVERGED', 'presentationScore': 1}


def test_compact_result_keeps_one_run_snapshot_and_ordered_references():
    inputs={'constraints': [{'metric':'meanIonEnergy','operator':'between','min':150,'max':160,'unit':'eV'}],
            'goals':[{'metric':'ionFlux','direction':'maximize'}]}
    source=[run(1,155,10),run(2,156,20),run(3,200,30)]
    result=search_reverse(inputs,source)
    assert result['searchResultVersion']==2
    assert [ref['runVersionId'] for ref in result['commonRunRefs']]==['2','1']
    assert set(result['runsByVersion'])=={'1','2'}
    assert not any(k in result for k in ['allMatches','candidates','commonCandidates','representativeCandidates','nearMatches','nearMisses'])
    assert validate_result(inputs,result,source)['valid']
    broken=deepcopy(result)
    broken['runsByVersion']['1']['metrics']['ionFlux']=999
    assert not validate_result(inputs,broken,source)['valid']


def test_no_match_does_not_return_nearest_runs():
    inputs={'constraints':[{'metric':'meanIonEnergy','operator':'between','min':150,'max':160,'unit':'eV'}]}
    result=search_reverse(inputs,[run(1,100,10),run(2,200,20)])
    assert result['resultStatus']=='NO_MATCH'
    assert result['commonRunRefs']==[]
    assert result['runsByVersion']=={}
    assert result['usedRunRefs']==[]


def test_relative_reference_roles_are_deduplicated_without_adding_catalog_references():
    from kplasma_agent.graphs.v1 import _reverse_context_refs
    ref = {"runId": "SYNTHETIC", "runVersionId": "immutable", "note": "extra"}
    assert _reverse_context_refs({"activeRun": ref, "selectedRunRef": ref,
                                  "candidateReferences": [{"runId": "OTHER", "runVersionId": "other"}]}) == [
        {"runId": "SYNTHETIC", "runVersionId": "immutable"}
    ]

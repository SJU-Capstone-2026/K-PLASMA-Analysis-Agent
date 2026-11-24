import pytest
from pydantic import ValidationError

from kplasma_agent.tools import CompareToolInputs, native_tools


def test_waveform_comparison_is_a_native_tool_argument_without_an_extra_tool():
    parsed = CompareToolInputs.model_validate({
        "comparison_fields": ["current.maximum", "current.halfPeakToPeak"],
        "plot_ids": ["current"],
    })
    assert parsed.comparison_fields == ["current.maximum", "current.halfPeakToPeak"]
    assert parsed.plot_ids == ["current"]
    assert len(native_tools()) == 5


@pytest.mark.parametrize("arguments", [
    {"comparison_fields": ["invented.energy"]},
    {"plot_ids": ["generated_curve"]},
    {"comparison_fields": ["ionFlux", "ionFlux"]},
    {"metrics": ["ionFlux"], "comparison_fields": ["meanIonEnergy"]},
])
def test_unknown_duplicate_or_conflicting_fields_cannot_execute(arguments):
    with pytest.raises(ValidationError):
        CompareToolInputs.model_validate(arguments)


def test_feature_comparison_uses_full_source_values_and_never_percent_for_coordinates():
    from fixtures import run
    from test_multi_run_compare import selected
    from kplasma_agent.domain.compare import compare_selected
    from kplasma_agent.answer_contracts import ComparisonResultV3
    entries = selected(run('A'), run('B'))
    outputs = []
    for index, entry in enumerate(entries):
        outputs.append({'metadata':{'ref':entry['ref'],'outputId':'current','status':'AVAILABLE','reason':None,
            'sourceIntegrity':f'synthetic-{index}','featurePolicyVersion':'source-features-1',
            'xUnit':'RF cycle','yUnit':'','valueUnit':'statampere/cm²','sourceCount':1001,'extrema':{'maximum':{'value':7,'x':.1,'y':None,'count':1}}},
            'features':{name:{'value':value,'unit':unit,'status':'AVAILABLE','reason':None,'sourceValue':None}
                        for name,value,unit in [('current.halfPeakToPeak',5+index,'statampere/cm²'),('current.maximumPhase',.1+index*.1,'RF cycle')]},'display':None})
    result = compare_selected({'comparison_fields':['current.halfPeakToPeak','current.maximumPhase'],'plot_ids':['current'],'baseline_key':'R1'}, entries, outputs)
    ComparisonResultV3.model_validate(result)
    assert result['comparisons'][0]['difference']['value']==1
    assert result['comparisons'][0]['percentChange']['value']==20
    assert result['comparisons'][1]['percentChange'] is None
    assert result['outputs'][0]['sourceCount']==1001
    assert 'display' not in str(result)
    bad = outputs[1]['features']['current.halfPeakToPeak']
    bad['unit']='A/m²'
    partial = compare_selected({'comparison_fields':['current.halfPeakToPeak']}, entries, outputs)
    assert partial['resultStatus']=='NO_COMPARABLE_DATA'

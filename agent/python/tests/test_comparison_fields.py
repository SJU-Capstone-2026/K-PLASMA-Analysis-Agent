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
    assert len(native_tools()) == 4


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


@pytest.mark.parametrize("question,unsupported", [
    ("전류 밀도 파형 피크와 진폭을 비교해줘", False),
    ("전류 밀도의 RMS를 비교해줘", True),
    ("전극 전위의 절댓값 피크를 비교해줘", True),
    ("전류 파형 위상차를 비교해줘", True),
])
def test_graph_loads_outputs_only_for_supported_source_features(question, unsupported):
    import json
    from pathlib import Path
    from kplasma_agent.graphs.v1 import build_graph
    from kplasma_agent.config import Settings
    from fixtures import run
    from test_multi_run_compare import selected
    wire=json.loads(Path('agent/tests/support/answer-v3-wire.json').read_text())
    entries=selected(*(run(ref['runId'],version=ref['runVersionId']) for ref in wire['comparison']['usedRunRefs']))
    context={'comparisonReference':{'entries':[{k:v for k,v in e.items() if k!='run'} | {'origin':{'kind':'run_tag','turnId':'synthetic','groupId':None,'pendingInputId':None}} for e in entries],'baselineKey':None}}
    class Backend:
        reads=0
        def stage(self,*args,**kwargs):pass
        def attempt(self,*args):pass
        def context(self,*args,**kwargs):return {'referencedRuns':[e['run'] for e in entries]}
        def comparison_outputs(self,refs,plots):
            self.reads+=1
            assert plots==['current']
            return {'outputs':[{**o,'display':None} for o in wire['outputs']]}
    class Model:
        def select_tool(self,*args):return wire['comparison']['toolSelection'],{'responseItems':[]}
        def generate(self,*args,**kwargs):return {'observationIds':['O1'],'interpretations':[],'limitations':[]},{}
    backend=Backend()
    graph=build_graph(Model(),backend,Settings(),None)
    value=graph.invoke({'request_id':'synthetic-request','question':question,'context':context,'input_history':[]})
    if unsupported:
        assert backend.reads == 0
        assert value['pending']['reason'] == 'UNSUPPORTED_COMPARISON_FEATURE'
        return
    assert backend.reads==1, (value.get("pending"),value.get("__interrupt__"))
    assert value['answer']['answerSnapshot']['schemaVersion']==3
    assert value['result']['runs'][0]['metrics']['current.maximum']['value']==4
    assert 'display' not in str(value['answer'])

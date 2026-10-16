from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from report import agent_summary,reduction


def test_failure_never_becomes_a_latency_improvement():
    failed=agent_summary([{'ok':False,'totalMs':60000}])
    assert failed['samples']==1 and failed['failures']==1 and failed['totalMsMean'] is None
    assert reduction(failed['totalMsMean'],1) is None


def test_leaf_segments_add_up_without_counting_parent_spans_twice():
    value=agent_summary([{'ok':True,'totalMs':100,'spans':[{'name':'agent.request','elapsedMs':100},{'name':'graph.gather','elapsedMs':40},{'name':'backend.context','elapsedMs':20},{'name':'backend.checkpoint','elapsedMs':10}]}])
    assert value['contextMsMean']==20
    assert value['checkpointMsMean']==10
    assert value['otherMsMean']==70

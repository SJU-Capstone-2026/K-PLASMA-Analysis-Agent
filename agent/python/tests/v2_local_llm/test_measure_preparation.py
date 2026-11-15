from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from evals import local_llm_measure as measurement
from kplasma_agent.v2_local_llm.config import Settings


def test_failed_d1_preparation_never_enters_cache_model_stages(monkeypatch):
    import json
    from evals import local_llm_cache_probe

    @contextmanager
    def client(*_a,**_k):
        yield SimpleNamespace(get=lambda _:SimpleNamespace(raise_for_status=lambda:None),
            post=lambda *_a,**_k:SimpleNamespace(raise_for_status=lambda:None,
                json=lambda:{"usage":{"input_tokens":3},"local_metrics":None}))
    monkeypatch.setattr(measurement,"local_http_client",client)
    monkeypatch.setattr(measurement,"verify_artifacts",lambda _:"fixed")
    monkeypatch.setattr(measurement,"live_facts",lambda _:"fixed")
    monkeypatch.setattr(measurement,"memory_sample",lambda:{"pressure":1,"swap_bytes":0,"resident_bytes":100})
    monkeypatch.setattr(measurement,"runtime_profile",lambda _: {})
    monkeypatch.setattr(measurement,"make_process_sampler",lambda _:lambda: {})
    def prepare(role):
        if role == "plan_review":
            raise ValueError("LOCAL_D1_MEMORY_NOT_RELEASED")
    monkeypatch.setattr(measurement,"ModelRuntime",lambda *_:SimpleNamespace(prepare=prepare))
    monkeypatch.setattr(measurement,"make_d1_counter",lambda *_:lambda *_:[1,1,1])
    monkeypatch.setattr(measurement,"make_qwen_counter",lambda *_:lambda *_:1)
    monkeypatch.setattr(measurement,"make_input_guard",lambda *_a,**_k:lambda *_:None)
    monkeypatch.setattr(measurement,"fit_input",lambda build,*_:build(1))
    monkeypatch.setattr(measurement,"ModelClient",lambda *_:SimpleNamespace(client=None,
        _json_request=lambda *_a,**_k:(json.dumps({"unit":"m⁻²s⁻¹"}),{"inputTokens":1,"reasoningPresent":False})))
    from kplasma_agent.v2_local_llm.core import model_gateway
    monkeypatch.setattr(model_gateway,"call_submit_plan",lambda _m,_i,data,*_: (
        json.loads(data)["plan"],{"inputTokens":1,"reasoningPresent":True}))
    monkeypatch.setattr(local_llm_cache_probe,"assert_probe_cache_empty",lambda _:None)
    monkeypatch.setattr(local_llm_cache_probe,"run_probe",lambda _:pytest.fail("cache invoked after release failure"))
    result=measurement.measure(Settings(qwen_plan_cache_enabled=True),
        {"data":"artificial-only","graphVersion":"v2_localLLM","url":"http://127.0.0.1:9998",
         "web":"http://127.0.0.1:9999"})
    assert result["passed"] is False
    d1_rows=[row for row in result["results"] if row["role"]=="d1"]
    assert len(d1_rows)==3
    assert all(row["error"]=="LOCAL_D1_MEMORY_NOT_RELEASED" for row in d1_rows)


def test_measurement_verifies_artifacts_before_contacting_the_stack(monkeypatch):
    def reject(_):
        raise ValueError("synthetic artifact mismatch")
    monkeypatch.setattr(measurement,"verify_artifacts",reject,raising=False)
    monkeypatch.setattr(measurement,"local_http_client",lambda *_a,**_k:pytest.fail("HTTP before artifact verification"))
    with pytest.raises(ValueError,match="synthetic artifact mismatch"):
        measurement.measure(Settings(),{"data":"artificial-only","graphVersion":"v2_localLLM", "url":"http://127.0.0.1:9998","web":"http://127.0.0.1:9999"})


def test_critical_pressure_stops_before_model_construction(monkeypatch):
    @contextmanager
    def health(*_a,**_k):
        yield SimpleNamespace(get=lambda _:SimpleNamespace(raise_for_status=lambda:None))
    monkeypatch.setattr(measurement,"local_http_client",health)
    monkeypatch.setattr(measurement,"verify_artifacts",lambda _:"fixed",raising=False)
    monkeypatch.setattr(measurement,"live_facts",lambda _:"fixed",raising=False)
    monkeypatch.setattr(measurement,"memory_sample",lambda:{"pressure":4,"swap_bytes":0,"resident_bytes":1})
    monkeypatch.setattr(measurement,"ModelClient",lambda *_:pytest.fail("model constructed during critical pressure"))
    with pytest.raises(ValueError,match="LOCAL_MEMORY_PRESSURE"):
        measurement.measure(Settings(),{"data":"artificial-only","graphVersion":"v2_localLLM", "url":"http://127.0.0.1:9998","web":"http://127.0.0.1:9999"})


def test_transient_critical_preparation_keeps_failed_report_and_error_code(monkeypatch):
    @contextmanager
    def health(*_a,**_k):
        yield SimpleNamespace(get=lambda _:SimpleNamespace(raise_for_status=lambda:None))
    class CriticalRuntime:
        def __init__(self,*_):
            pass
        def prepare(self,_):
            raise ValueError('LOCAL_MEMORY_CRITICAL')
    monkeypatch.setattr(measurement,'local_http_client',health)
    monkeypatch.setattr(measurement,'verify_artifacts',lambda _:'fixed')
    monkeypatch.setattr(measurement,'live_facts',lambda _:'fixed')
    monkeypatch.setattr(measurement,'memory_sample',lambda:{'pressure':1,'swap_bytes':0,'resident_bytes':100})
    monkeypatch.setattr(measurement,'ModelClient',lambda *_:SimpleNamespace(client=None))
    monkeypatch.setattr(measurement,'ModelRuntime',CriticalRuntime)
    result=measurement.measure(Settings(),{'data':'artificial-only','graphVersion':'v2_localLLM',
        'url':'http://127.0.0.1:9998','web':'http://127.0.0.1:9999'})
    assert result['passed'] is False
    assert result['results'][0]['error']=='LOCAL_MEMORY_CRITICAL'
    assert result['samples']


def test_artificial_fitter_reduces_input_when_exact_counter_refuses_oversize():
    import httpx
    def count(n):
        if n>40:
            response=httpx.Response(422,request=httpx.Request('POST','http://127.0.0.1:8083/v1/count'),
                json={'error':{'code':'LOCAL_D1_INPUT_TOO_LARGE'}})
            response.raise_for_status()
        return n
    assert measurement.fit_input(lambda n:n,count,100)==40


def test_artificial_fitter_does_not_treat_auth_failure_as_an_input_size():
    import httpx
    def count(_):
        httpx.Response(401,request=httpx.Request('POST','http://127.0.0.1:8083/v1/count')).raise_for_status()
    with pytest.raises(httpx.HTTPStatusError):
        measurement.fit_input(lambda n:n,count,100)


def test_process_sampler_records_role_rss_in_bytes(monkeypatch):
    def output(args,**kwargs):
        if args[0].endswith('lsof'):
            return 'p11\n' if '-iTCP:8082' in args else 'p22\n'
        return '11 100\n22 200\n'
    import subprocess
    monkeypatch.setattr(subprocess,'check_output',output)
    sampler=measurement.make_process_sampler(Settings())
    assert sampler()=={'qwen':102400,'d1':204800}

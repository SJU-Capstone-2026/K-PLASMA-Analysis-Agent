import json

import httpx
import pytest

from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.model_client import ModelClient
from kplasma_agent.v2_local_llm.core.contracts import GeneralAnswerDraft


def test_qwen_json_uses_only_local_endpoint_and_retains_strict_answer_contract():
    seen = []
    def respond(request):
        seen.append(request)
        payload = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:8082/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-qwen"
        assert payload["store"] is False and payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 0,
            "model": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"paragraphs":["IED는 이온 에너지 분포입니다."],"sources":[]}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22}})
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        model = ModelClient(Settings(api_key="synthetic-qwen"), http_client=client)
        result, usage = model.generate("인공 테스트", {"question": "IED란?"}, GeneralAnswerDraft)
    assert result == {"paragraphs": ["IED는 이온 에너지 분포입니다."], "sources": []}
    assert usage["inputTokens"] == 10 and len(seen) == 1


def test_external_model_url_is_rejected_before_openai_client_creation():
    with pytest.raises(ValueError, match="LOCAL_ENDPOINT_INVALID"):
        ModelClient(Settings(api_key="synthetic", model_url="https://api.openai.com/v1"))


def test_default_backend_and_qwen_clients_do_not_use_ambient_proxies(monkeypatch):
    from kplasma_agent.v2_local_llm.backend_client import BackendClient
    monkeypatch.setenv("HTTPS_PROXY", "http://outside.invalid:9090")
    backend = BackendClient(Settings())
    assert backend.client.trust_env is False
    backend.client.close()
    model = ModelClient(Settings(api_key="synthetic"))
    assert str(model.client.base_url) == "http://127.0.0.1:8082/v1/"
    assert model.client._client.trust_env is False
    model.client.close()


def test_native_planner_timings_are_numeric_and_do_not_copy_extra_content():
    from types import SimpleNamespace
    def respond(request):
        return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':0,'model':'synthetic',
         'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
          'tool_calls':[{'id':'call','type':'function','function':{'name':'submit_plan','arguments':'{}'}}]}}],
         'usage':{'prompt_tokens':12,'completion_tokens':2,'total_tokens':14},
         'timings':{'cache_n':10,'prompt_n':2,'prompt_ms':3.5,'predicted_n':2,'predicted_ms':1.5,'private':'secret'}})
    span=SimpleNamespace(attribute=lambda *_:None,json_attribute=lambda *_:None)
    with httpx.Client(transport=httpx.MockTransport(respond),trust_env=False) as client:
        model=ModelClient(Settings(api_key='synthetic'),http_client=client)
        _,usage=model._tool_request('인공','{}',{'type':'function','name':'submit_plan','parameters':{}},span)
    assert usage['nativeTimings']=={'cache_n':10,'prompt_n':2,'prompt_ms':3.5,'predicted_n':2,'predicted_ms':1.5}

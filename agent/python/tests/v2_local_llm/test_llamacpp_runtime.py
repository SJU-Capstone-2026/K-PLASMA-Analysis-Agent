import json
from dataclasses import replace

import httpx
import pytest

from kplasma_agent.v2_local_llm import runtime
from kplasma_agent.v2_local_llm.core import budget
from kplasma_agent.v2_local_llm.config import Settings
from kplasma_agent.v2_local_llm.network import local_http_client


def props(settings, *, sleeping=True, path=None):
    return {"model_path":path or settings.model_path,"total_slots":1,
            "default_generation_settings":{"n_ctx":settings.context_tokens},"is_sleeping":sleeping}


@pytest.mark.parametrize("role", ["plan","answer","review","plan_review"])
def test_role_switch_releases_d1_or_waits_for_qwen_without_waking_either(role, monkeypatch):
    settings=Settings(model_path="/synthetic/qwen.gguf")
    events=[]
    waiting=iter([False,True])
    def handle(request):
        events.append((request.method,request.url.port,request.url.path))
        if request.url.port==8083:
            assert request.method=="POST" and request.url.path=="/unload"
            return httpx.Response(200,json={"engine":"mlx-decision","released":True,"loaded":False,
                "memory":{"active_bytes":100,"cache_bytes":0},"idle_active_bytes":100})
        assert request.method=="GET" and request.url.path=="/props"
        return httpx.Response(200,json=props(settings,
            sleeping=next(waiting) if role in {"review","plan_review"} else True))
    monkeypatch.setattr(runtime.time,"sleep",lambda _:None)
    with local_http_client(settings.model_url,timeout=5,transport=httpx.MockTransport(handle)) as qwen, \
         local_http_client(settings.d1_url,timeout=5,transport=httpx.MockTransport(handle)) as d1:
        runtime.ModelRuntime(settings,qwen,d1).prepare(role)
    if role in {"plan","answer"}:
        assert events==[("GET",8082,"/props"),("POST",8083,"/unload")]
    else:
        assert events==[("GET",8082,"/props")]*2


def test_wrong_qwen_path_is_rejected_without_unloading_other_model():
    settings=Settings(model_path="/synthetic/qwen.gguf")
    def handle(request):
        assert request.method=="GET"
        return httpx.Response(200,json=props(settings,path="/synthetic/other.gguf"))
    with local_http_client(settings.model_url,timeout=5,transport=httpx.MockTransport(handle)) as qwen, \
         local_http_client(settings.d1_url,timeout=5,transport=httpx.MockTransport(handle)) as d1:
        with pytest.raises(ValueError,match="LOCAL_QWEN_MODEL_MISMATCH"):
            runtime.ModelRuntime(settings,qwen,d1).prepare("review")


@pytest.mark.parametrize("role,thinking",[("plan",True),("answer",False)])
def test_native_qwen_counter_uses_actual_template_and_special_tokens(role,thinking):
    def handle(request):
        body=json.loads(request.content)
        if request.url.path=="/apply-template":
            assert body["chat_template_kwargs"]=={"enable_thinking":thinking}
            assert body["messages"][1]["content"]=="인공 m⁻²s⁻¹"
            assert body["tools"][0]["function"]["name"]=="submit_plan"
            return httpx.Response(200,json={"prompt":"<|im_start|>인공"})
        assert request.url.path=="/tokenize"
        assert body=={"content":"<|im_start|>인공","add_special":False,"parse_special":True}
        return httpx.Response(200,json={"tokens":[1,2,3]})
    settings=Settings()
    with local_http_client(settings.model_url,timeout=5,transport=httpx.MockTransport(handle)) as client:
        count=budget.make_qwen_counter(settings,client)
        assert count({"instructions":"검사","input":"인공 m⁻²s⁻¹","tools":[{
            "type":"function","name":"submit_plan","parameters":{"type":"object"}}]},role)==3


def test_runtime_profile_is_independent_of_app_addresses_and_bound_to_thinking(monkeypatch):
    monkeypatch.setattr(runtime,"_mlx_libraries",lambda *_:"a"*64)
    settings=Settings()
    profile=runtime.runtime_profile(settings)
    assert runtime.runtime_profile(replace(settings,backend_url="http://127.0.0.1:9999",worker_token="other"))==profile
    assert runtime.runtime_profile(replace(settings,reasoning_effort="none"))!=profile


@pytest.mark.parametrize("bad", [None, "batch", "ubatch", "duplicate", "executable", "cache", "cache-wrong", "cache-unexpected"])
def test_runtime_requires_the_256_batch_profile_and_pinned_executable(tmp_path, monkeypatch, bad):
    import shlex
    key=tmp_path/"key"
    key.write_text("synthetic")
    settings=Settings(api_key="synthetic",model_path="/synthetic/qwen.gguf")
    options={"--model":settings.model_path,"--alias":settings.model,"--api-key-file":str(key),
        "--host":"127.0.0.1","--port":"8082","--ctx-size":str(settings.context_tokens),"--batch-size":"256",
        "--ubatch-size":"256","--parallel":"1","--sleep-idle-seconds":"1","--device":"MTL0",
        "--gpu-layers":"all","--fit":"off","--timeout":"90","--reasoning":"auto",
        "--reasoning-format":"deepseek","--reasoning-budget":"2048"}
    if bad in {"cache", "cache-wrong"}:
        settings=replace(settings,qwen_plan_cache_enabled=True,qwen_plan_cache_dir=str(tmp_path/"cache"))
        options["--slot-save-path"]=str(tmp_path/("wrong" if bad=="cache-wrong" else "cache"))
    if bad=="cache-unexpected":
        options["--slot-save-path"]=str(tmp_path/"cache")
    if bad in {"batch", "ubatch"}:
        options["--batch-size" if bad == "batch" else "--ubatch-size"] = "512"
    binary="/synthetic/other-server" if bad=="executable" else "/synthetic/llama-server"
    args=[binary,*[part for item in options.items() for part in item],
          "--jinja","--offline","--no-context-shift","--no-webui"]
    if bad=="duplicate":
        args += ["--reasoning-budget","0"]
    def output(command,**kwargs):
        if command[0].endswith("lsof"):
            return "p123\n"
        return binary if command[-1]=="comm=" else shlex.join(args)
    monkeypatch.setattr(runtime.subprocess,"check_output",output)
    manifest=json.loads(runtime.Path(runtime.__file__).with_name("runtime-manifest.json").read_text())
    monkeypatch.setattr(runtime,"_hash",lambda p:manifest["qwenRuntimeFiles"].get(p.name,"wrong-executable"))
    if bad in {None, "cache"}:
        assert runtime._server_facts(settings,settings.model_url,settings.model_path,qwen=True).startswith("123")
    else:
        with pytest.raises(ValueError):
            runtime._server_facts(settings,settings.model_url,settings.model_path,qwen=True)

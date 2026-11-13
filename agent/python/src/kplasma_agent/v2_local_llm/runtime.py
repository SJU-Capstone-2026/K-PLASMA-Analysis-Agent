"""Local runtime facts; no cloud clients or operating-system network changes."""

import re
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from functools import lru_cache
import hashlib
import json
import shlex
import subprocess
import time
import tempfile
from dataclasses import replace

import httpx

from .network import local_http_client, validate_endpoint
from .core.budget import MAX_INPUT_TOKENS

PROFILE_FIELDS = ("model_revision", "d1_revision", "runtime_version", "d1_runtime_version", "context_tokens",
                  "d1_context_tokens", "d1_batch_tokens", "d1_ubatch_tokens")
_VERIFIED_CONTRACTS: set[tuple[str, str, str]] = set()
QWEN_RUNTIME_OPTIONS = {"--batch-size": 256, "--ubatch-size": 256, "--parallel": 1,
                        "--device": "MTL0", "--gpu-layers": "all", "--fit": "off",
                        "--sleep-idle-seconds": 1, "--reasoning": "auto",
                        "--reasoning-format": "deepseek", "--reasoning-budget": 2048}


class ModelRuntimeBusy(ValueError):
    def __init__(self):
        super().__init__("LOCAL_MODEL_RUNTIME_BUSY")


@contextmanager
def model_lease():
    # Worker, evaluation and status probes share one pair of local model servers.
    try:
        fd = os.open(Path(tempfile.gettempdir()) / "kplasma-v2-local-llm-models.lock",
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise ValueError("LOCAL_MODEL_LOCK_UNAVAILABLE") from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ModelRuntimeBusy() from None
        except OSError:
            raise ValueError("LOCAL_MODEL_LOCK_UNAVAILABLE") from None
        yield
    finally:
        os.close(fd)


@lru_cache(maxsize=128)
def _file_hash(path, size, modified, inode, changed):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _hash(path):
    stat = path.stat()
    return _file_hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_ctime_ns)


def verify_artifacts(settings):
    try:
        manifest = json.loads(Path(__file__).with_name("runtime-manifest.json").read_text())
        q = manifest["qwen"]
        if (settings.model_revision != q["revision"] or settings.model != q["alias"]
                or settings.d1_model != manifest["d1"]["source"] + ":Q8_0"
                or settings.d1_revision != manifest["d1"]["revision"]
                or settings.runtime_version != manifest["qwenRuntimeVersion"]
                or settings.d1_runtime_version != manifest["d1"]["runtimeVersion"]):
            raise ValueError
        qwen_hash, d1_hash = _hash(Path(settings.model_path)), _hash(Path(settings.d1_model_path))
        if qwen_hash != q["modelSha256"] or d1_hash != manifest["d1"]["modelSha256"]:
            raise ValueError
        return qwen_hash + d1_hash
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("LOCAL_MODEL_ARTIFACT_MISMATCH") from None


def runtime_profile(settings):
    versions = settings.versions()
    return {**{key: getattr(settings, key) for key in PROFILE_FIELDS},
            "qwenRuntimeOptions": dict(QWEN_RUNTIME_OPTIONS),
            **{key: versions[key] for key in ("planner", "writer", "decisions", "quantization",
                "d1Quantization", "runtimeManifestHash", "qwenGeneration")}}


def verify_memory_report(settings):
    try:
        report = json.loads(Path(settings.measurement_path).read_text())
        profile = runtime_profile(settings)
        if (report["schema_version"] != 1 or report["synthetic_only"] is not True
                or report["full_stack"] is not True or report["runtime_profile"] != profile):
            raise ValueError
        if (not re.fullmatch(r"[a-f0-9]{64}", report["instance_facts_before"])
                or report["instance_facts_before"] != report["instance_facts_after"]):
            raise ValueError
        rows, samples = report["results"], report["samples"]
        if (len(rows) != 7 or len(samples) < 3
                or {(row["role"], row["target"]) for row in rows}
                != ({(role, target) for role in ("qwen", "d1") for target in (256, 4096, MAX_INPUT_TOKENS - 500)}
                    | {("qwen_plan", MAX_INPUT_TOKENS - 500)})
                or any(row["passed"] is not True or not 0 < row["seconds"] <= 90
                       or not row["target"] * 0.9 <= row["counted"] <= MAX_INPUT_TOKENS for row in rows)
                or any(row["input_tokens"] != (sum(row["question_counts"]) if row["role"] == "d1"
                                               else row["counted"]) for row in rows)
                or any(row["reasoning_present"] is not (row["role"] == "qwen_plan")
                       for row in rows if row["role"] != "d1")
                or any(sample["pressure"] != 1 or type(sample["swap_bytes"]) is not int
                       or sample["swap_bytes"] < 0 or sample["resident_bytes"] <= 0 for sample in samples)
                or max(sample["swap_bytes"] for sample in samples) > samples[0]["swap_bytes"]):
            raise ValueError
        return hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("LOCAL_MEMORY_EVIDENCE_INVALID") from None


def _server_facts(settings, url, model_path, *, qwen=False):
    port = httpx.URL(url).port
    listeners = subprocess.check_output(["/usr/sbin/lsof", "-nP", "-iTCP:" + str(port),
                                         "-sTCP:LISTEN", "-Fp"], text=True, timeout=5)
    pids = {line[1:] for line in listeners.splitlines() if line.startswith("p")}
    if len(pids) != 1:
        raise ValueError
    pid = next(iter(pids))
    binary = Path(subprocess.check_output(["/bin/ps", "-p", pid, "-o", "comm="], text=True, timeout=5).strip())
    args = shlex.split(subprocess.check_output(["/bin/ps", "-p", pid, "-o", "command="], text=True, timeout=5))
    required = {"--ctx-size": settings.context_tokens if qwen else settings.d1_context_tokens,
                "--batch-size": QWEN_RUNTIME_OPTIONS["--batch-size"] if qwen else settings.d1_batch_tokens,
                "--ubatch-size": QWEN_RUNTIME_OPTIONS["--ubatch-size"] if qwen else settings.d1_ubatch_tokens,
                "--parallel": 1, "--sleep-idle-seconds": 1,
                "--device": "MTL0", "--gpu-layers": "all", "--host": httpx.URL(url).host,
                "--fit": "off", "--port": port, "--timeout": 90}
    flags = {"--offline", "--no-context-shift", "--no-webui"}
    if qwen:
        required.update(QWEN_RUNTIME_OPTIONS)
        required.update({"--alias": settings.model, "--reasoning": "auto", "--reasoning-format": "deepseek",
                         "--reasoning-budget": 2048})
        flags.add("--jinja")
    allowed = set(required) | flags | {"--model", "--api-key-file"}
    if (any(args.count(key) != 1 for key in allowed)
            or any(str(value) != args[args.index(key) + 1] for key, value in required.items())
            or not flags.issubset(args)
            or any(arg.startswith("-") and arg not in allowed for arg in args[1:])
            or Path(args[args.index("--model")+1]).resolve() != Path(model_path).resolve()
            or Path(args[args.index("--api-key-file")+1]).read_text().strip()
                != (settings.api_key if qwen else settings.d1_token)):
        raise ValueError
    manifest = json.loads(Path(__file__).with_name("runtime-manifest.json").read_text())
    if _hash(binary) != manifest["d1BinarySha256"]:
        raise ValueError
    for name, digest in manifest["d1RuntimeFiles"].items():
        if _hash(binary.parent / name) != digest:
            raise ValueError
    return pid + " ".join(args)


def live_facts(settings):
    try:
        for url in (settings.backend_url, settings.model_url, settings.d1_url):
            validate_endpoint(url)
        with local_http_client(settings.model_url, timeout=5,
                               headers={"Authorization": "Bearer " + settings.api_key}) as qwen, \
             local_http_client(settings.d1_url, timeout=5,
                               headers={"Authorization": "Bearer " + settings.d1_token}) as d1:
            props = ModelRuntime(settings, qwen, d1)._models()
            expected_template = json.loads(Path(__file__).with_name("runtime-manifest.json").read_text())["qwen"]["chatTemplateSha256"]
            if hashlib.sha256(props["chat_template"].encode()).hexdigest() != expected_template:
                raise ValueError
            response = d1.get(httpx.URL(settings.d1_url).copy_with(path="/props"))
            response.raise_for_status()
            data = response.json()
            if (data["default_generation_settings"]["n_ctx"] != settings.d1_context_tokens
                    or data["total_slots"] != 1 or Path(data["model_path"]).resolve() != Path(settings.d1_model_path).resolve()):
                raise ValueError
        return (_server_facts(settings, settings.model_url, settings.model_path, qwen=True)
                + _server_facts(settings, settings.d1_url, settings.d1_model_path)
                + settings.versions()["configFingerprint"])
    except (OSError, ValueError, KeyError, TypeError, IndexError, httpx.HTTPError, subprocess.SubprocessError):
        raise ValueError("LOCAL_RUNTIME_PROFILE_MISMATCH") from None


def contract_probe(settings):
    from .core.budget import make_qwen_counter, make_d1_counter
    from .core.contracts import GeneralAnswerDraft, PlanDraft
    from .core.decisions import native_request, normalize_response
    from .core.model_gateway import call_submit_plan, submit_plan_tool_schema
    from .model_client import ModelClient, strict_schema
    from . import tracing
    unit = "m⁻²s⁻¹"
    plan = PlanDraft.model_validate({"schema_version": 2, "request_mode": "general_only", "base_revision": None,
        "requirements": [{"id": "unit", "text": "인공 준비 검사", "handled_by": ["explain"],
                          "sources": [{"message_key": "question", "quote": "인공 준비 검사"}]}],
        "steps": [{"id": "explain", "kind": "tool", "tool": "explain_answer",
                   "requirement_ids": ["unit"], "inputs": {"mode": "concept"}}]})
    with local_http_client(settings.model_url, timeout=90,
                           headers={"Authorization": "Bearer " + settings.api_key}) as qwen, \
            local_http_client(settings.d1_url, timeout=90,
                              headers={"Authorization": "Bearer " + settings.d1_token}) as d1:
        runtime = ModelRuntime(settings, qwen, d1)
        runtime.prepare("plan")
        model = ModelClient(settings)
        try:
            with tracing.span("local.synthetic.readiness", kind="LLM") as span:
                native_plan, plan_usage = call_submit_plan(model,
                    "인공 준비 검사입니다. 주어진 계획을 submit_plan으로 동일하게 한 번 제출하세요.",
                    plan.model_dump_json(), submit_plan_tool_schema())
                counter = make_qwen_counter(settings, qwen)
                if (PlanDraft.model_validate(native_plan) != plan or not plan_usage.get("reasoningPresent") or counter({
                        "instructions": "인공 준비 검사입니다. 주어진 계획을 submit_plan으로 동일하게 한 번 제출하세요.",
                        "input": plan.model_dump_json(), "tools": [submit_plan_tool_schema()]}, "plan") != plan_usage["inputTokens"]):
                    raise ValueError
                instructions = "인공 준비 검사입니다. 입력을 paragraphs 하나에 그대로 반환하고 sources는 빈 배열로 반환하세요."
                writer_payload = {"instructions": instructions, "input": unit, "schema": strict_schema(GeneralAnswerDraft)}
                fragments: list[str] = []
                counter = make_qwen_counter(settings, qwen)
                model.settings = replace(settings, reasoning_effort="none")
                for streaming in (False, True):
                    text, usage = model._json_request(instructions, unit, strict_schema(GeneralAnswerDraft), span,
                                                     max_output_tokens=3000,
                                                     on_text_delta=fragments.append if streaming else None)
                    if (GeneralAnswerDraft.model_validate_json(text).paragraphs != [unit]
                            or usage.get("reasoningPresent")
                            or counter(writer_payload, "answer") != usage["inputTokens"]):
                        raise ValueError
                if "".join(fragments) != text:
                    raise ValueError
        finally:
            if model.client is not None:
                model.client.close()
        runtime.prepare("plan_review")
        questions = [{"name": "unit", "type": "choice", "instructions": "unit는 m⁻²s⁻¹인가?", "choices": [
            {"value": "same", "description": "같음"}, {"value": "changed", "description": "다름"}]}]
        decision_payload = {"input": {"unit": unit}, "questions": questions}
        counts = make_d1_counter(settings, d1)(decision_payload, "plan_review")
        native = native_request({"input": [{"role": "user", "content": [
            {"type": "input_json", "data": decision_payload["input"]}]}], "questions": questions})
        response = d1.post(settings.d1_url, json=native)
        response.raise_for_status()
        result = normalize_response(response.content, native["questions"])
        if result["answers"][0]["choice"] != "same" or result["usage"]["input_tokens"] != sum(counts):
            raise ValueError


def wait_for_stability(settings):
    deadline = time.monotonic() + 60
    stable_since = None
    try:
        with local_http_client(settings.model_url, timeout=2,
                               headers={"Authorization": "Bearer " + settings.api_key}) as qwen, \
                local_http_client(settings.d1_url, timeout=2,
                                  headers={"Authorization": "Bearer " + settings.d1_token}) as d1:
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError("LOCAL_MEMORY_PRESSURE")
                pressure = memory_sample(deadline=deadline)["pressure"]
                if pressure == 4:
                    raise ValueError("LOCAL_MEMORY_CRITICAL")
                idle = True
                for client, url in ((qwen, settings.model_url), (d1, settings.d1_url)):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("LOCAL_MEMORY_PRESSURE")
                    response = client.get(httpx.URL(url).copy_with(path="/props"), timeout=min(2, remaining))
                    response.raise_for_status()
                    try:
                        data = response.json()
                    except ValueError:
                        raise ValueError("LOCAL_MODEL_RUNTIME_UNAVAILABLE") from None
                    if not isinstance(data, dict):
                        raise ValueError("LOCAL_MODEL_RUNTIME_UNAVAILABLE")
                    idle = idle and data.get("is_sleeping") is True
                now = time.monotonic()
                if now > deadline:
                    raise ValueError("LOCAL_MEMORY_PRESSURE")
                if idle and pressure == 1:
                    stable_since = now if stable_since is None else stable_since
                    if now - stable_since >= 5:
                        return
                else:
                    stable_since = None
                if now >= deadline:
                    raise ValueError("LOCAL_MEMORY_PRESSURE")
                time.sleep(min(1, deadline - now))
    except (httpx.HTTPError, OSError, KeyError, TypeError):
        raise ValueError("LOCAL_MODEL_RUNTIME_UNAVAILABLE") from None


def check_readiness(settings):
    blockers = []
    if not all((settings.api_key, settings.d1_token, settings.worker_token)):
        blockers.append("LOCAL_TOKENS_NOT_CONFIGURED")
    if not all(path and Path(path).exists() for path in (settings.model_path, settings.d1_model_path)):
        blockers.append("LOCAL_MODELS_NOT_PREPARED")
    if not all((settings.model_revision, settings.d1_revision, settings.runtime_version, settings.d1_runtime_version)):
        blockers.append("LOCAL_MODEL_VERSIONS_UNPINNED")
    if not settings.measurement_path:
        blockers.append("LOCAL_MEMORY_EVIDENCE_REQUIRED")
    if blockers:
        return {"ready": False, "blockers": blockers}
    try:
        if ((settings.api_key.startswith("sk-") and not settings.api_key.startswith("sk-lm-"))
                or settings.d1_token.startswith("sk-")):
            raise ValueError("LOCAL_CLOUD_CREDENTIAL_REJECTED")
        assets = verify_artifacts(settings)
        measured = verify_memory_report(settings)
        facts = live_facts(settings)
        pressure = memory_sample()["pressure"]
        if pressure == 4:
            raise ValueError("LOCAL_MEMORY_CRITICAL")
        if pressure != 1:
            raise ValueError("LOCAL_MEMORY_PRESSURE")
        key = (assets, measured, facts)
        if key not in _VERIFIED_CONTRACTS:
            with model_lease():
                try:
                    contract_probe(settings)
                except Exception:
                    raise ValueError("LOCAL_MODEL_CONTRACT_UNVERIFIED") from None
                wait_for_stability(settings)
            _VERIFIED_CONTRACTS.add(key)
        pressure = memory_sample()["pressure"]
        if pressure == 4:
            raise ValueError("LOCAL_MEMORY_CRITICAL")
        if pressure != 1:
            raise ValueError("LOCAL_MEMORY_PRESSURE")
        return {"ready": True, "blockers": []}
    except ValueError as error:
        return {"ready": False, "blockers": [str(error)]}


class ModelRuntime:
    """Keep one model resident on 24GB; the graph and native decisions remain unchanged."""

    def __init__(self, settings, qwen, d1):
        self.settings, self.qwen, self.d1 = settings, qwen, d1

    def _url(self, base, path):
        return httpx.URL(base).copy_with(path=path)

    def _models(self):
        response = self.qwen.get(self._url(self.settings.model_url, "/props"))
        response.raise_for_status()
        data = response.json()
        if (Path(data.get("model_path", "")).resolve() != Path(self.settings.model_path).resolve()
                or data.get("total_slots") != 1
                or data.get("default_generation_settings", {}).get("n_ctx") != self.settings.context_tokens):
            raise ValueError("LOCAL_QWEN_MODEL_MISMATCH")
        return data

    def prepare(self, role):
        try:
            self._models()
            if role in {"plan", "answer"}:
                client, url, code = self.d1, self.settings.d1_url, "LOCAL_D1_MEMORY_NOT_RELEASED"
            elif role in {"review", "plan_review"}:
                client, url, code = self.qwen, self.settings.model_url, "LOCAL_QWEN_MEMORY_NOT_RELEASED"
            else:
                raise ValueError("LOCAL_BUDGET_ROLE_INVALID")
            deadline = time.monotonic() + 12
            while True:
                response = client.get(self._url(url, "/props"))
                response.raise_for_status()
                if response.json().get("is_sleeping") is True:
                    return
                if time.monotonic() >= deadline:
                    raise ValueError(code)
                time.sleep(0.2)
        except (httpx.HTTPError, OSError, subprocess.SubprocessError, KeyError, TypeError):
            raise ValueError("LOCAL_MODEL_RUNTIME_UNAVAILABLE") from None


def parse_memory_sample(sysctl, vmstat):
    try:
        pressure = int(re.findall(r"pressure_level:\s*(\d+)", sysctl)[0])
        swap = float(re.findall(r"used\s*=\s*([\d.]+)M", sysctl)[0])
        page_size = int(re.findall(r"page size of (\d+) bytes", vmstat)[0])
        matched = re.findall(r"(?:Pages active|Pages wired down|Pages occupied by compressor):\s*(\d+)", vmstat)
        if len(matched) != 3:
            raise ValueError
        pages = sum(map(int, matched))
        if pressure not in {1, 2, 4} or not 0 <= swap < 1048576 or page_size <= 0:
            raise ValueError
        return {"pressure": pressure, "swap_bytes": int(swap * 1024**2), "resident_bytes": pages * page_size}
    except (ValueError, TypeError, IndexError):
        raise ValueError("LOCAL_MEMORY_MEASUREMENT_UNAVAILABLE") from None


def memory_sample(*, deadline=None):
    try:
        remaining = 5 if deadline is None else min(5, deadline - time.monotonic())
        if remaining <= 0:
            raise ValueError("LOCAL_MEMORY_PRESSURE")
        ctl = subprocess.run(["/usr/sbin/sysctl", "vm.swapusage", "kern.memorystatus_vm_pressure_level"],
                             capture_output=True, text=True, check=True, timeout=remaining)
        remaining = 5 if deadline is None else min(5, deadline - time.monotonic())
        if remaining <= 0:
            raise ValueError("LOCAL_MEMORY_PRESSURE")
        vm = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, check=True, timeout=remaining)
        return parse_memory_sample(ctl.stdout, vm.stdout)
    except (OSError, subprocess.SubprocessError):
        if deadline is not None and time.monotonic() >= deadline:
            raise ValueError("LOCAL_MEMORY_PRESSURE") from None
        raise ValueError("LOCAL_MEMORY_MEASUREMENT_UNAVAILABLE") from None

"""Optional Phoenix observations. Never use trace data as execution or recovery state."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
from urllib.parse import urlsplit

LOG = logging.getLogger("kplasma.tracing")
_provider = None
_tracer = None
_secrets: tuple[str, ...] = ()
_session: ContextVar[str | None] = ContextVar("kplasma_trace_session", default=None)
_credential_keys = {"apikey", "authorization", "password", "token", "workertoken", "xagenttoken"}


def _register(**kwargs):
    from phoenix.otel import register
    return register(**kwargs)


def initialize(settings):
    global _provider, _tracer, _secrets
    if not settings.phoenix_endpoint and not settings.phoenix_api_key:
        return False
    try:
        url = urlsplit(settings.phoenix_endpoint)
        valid = (settings.phoenix_api_key and url.scheme in ("http", "https") and url.hostname
                 and not (url.username or url.password or url.query or url.fragment))
    except ValueError:
        valid = False
    if not valid:
        LOG.warning("PHOENIX_CONFIG_INVALID: set collector endpoint and API key")
        return False
    endpoint = settings.phoenix_endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint += "/v1/traces"
    _secrets = tuple(v for v in (settings.api_key, settings.worker_token, settings.phoenix_api_key) if v)
    try:
        _provider = _register(
            endpoint=endpoint, project_name=settings.phoenix_project_name,
            protocol="http/protobuf", api_key=settings.phoenix_api_key,
            batch=True, set_global_tracer_provider=False, auto_instrument=False, verbose=False,
        )
        _tracer = _provider.get_tracer("kplasma.graph.v1")
    except Exception:
        _provider = _tracer = None
        LOG.warning("PHOENIX_SETUP_FAILED: install the tracing extra and check configuration")
        return False
    LOG.info("Phoenix tracing ready: project=%s", settings.phoenix_project_name)
    return True


def shutdown():
    global _provider, _tracer
    provider, _provider, _tracer = _provider, None, None
    if provider is not None:
        for finish in (lambda: provider.force_flush(timeout_millis=3000), provider.shutdown):
            try:
                finish()
            except Exception:
                LOG.warning("PHOENIX_FLUSH_FAILED")


def _scrub(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if rekey(key) in _credential_keys else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        for secret in _secrets:
            value = value.replace(secret, "[REDACTED]")
    return value


def rekey(value):
    return str(value).lower().replace("_", "").replace("-", "")


def _json(value):
    return json.dumps(_scrub(value), ensure_ascii=False, default=lambda obj: f"<{type(obj).__name__}>")


class Observation:
    def __init__(self, raw=None):
        self.raw = raw
        self.failed = False

    def attribute(self, key, value):
        if self.raw is not None:
            try:
                self.raw.set_attribute(key, _scrub(value))
            except Exception:
                pass

    def json_attribute(self, key, value):
        if self.raw is not None:
            try:
                self.raw.set_attribute(key, _json(value() if callable(value) else value))
            except Exception:
                pass

    def output(self, value):
        self.json_attribute("output.value", value)
        self.attribute("output.mime_type", "application/json")

    def error(self, error):
        self.failed = True
        code = getattr(error, "code", None)
        if not isinstance(code, str) or not code.replace("_", "").isupper() or len(code) > 80:
            code = type(error).__name__
        self.attribute("error.code", code)
        if self.raw is not None:
            try:
                from opentelemetry.trace import Status, StatusCode
                self.raw.set_status(Status(StatusCode.ERROR, _scrub(code)))
            except Exception:
                pass

    def success(self):
        if self.raw is not None and not self.failed:
            try:
                from opentelemetry.trace import Status, StatusCode
                self.raw.set_status(Status(StatusCode.OK))
            except Exception:
                pass


@contextmanager
def span(name, *, kind="CHAIN", inputs=None, attributes=None, session_id=None):
    scope = None
    observed = Observation()
    token = _session.set(session_id) if session_id else None
    try:
        if _tracer is not None:
            try:
                scope = _tracer.start_as_current_span(
                    name, record_exception=False, set_status_on_exception=False,
                    attributes={"openinference.span.kind": kind},
                )
                observed = Observation(scope.__enter__())
            except Exception:
                scope = None
        if _session.get():
            observed.attribute("session.id", _session.get())
        for key, value in (attributes or {}).items():
            observed.attribute(key, value)
        if inputs is not None:
            observed.json_attribute("input.value", inputs)
            observed.attribute("input.mime_type", "application/json")
        try:
            yield observed
        except BaseException as error:
            if type(error).__name__ in ("GraphInterrupt", "NodeInterrupt"):
                observed.attribute("kplasma.outcome", "NEEDS_INPUT")
            else:
                observed.error(error)
            raise
    finally:
        observed.success()
        if scope is not None:
            try:
                scope.__exit__(None, None, None)
            except Exception:
                pass
        if token is not None:
            _session.reset(token)


def node(name, fn):
    @wraps(fn)
    def observed(state):
        kind = state.get("operation", {}).get("kind", "")
        with span(f"graph.{name}", kind="TOOL" if name == "calculate" else "CHAIN",
                  inputs=state, attributes={"kplasma.operation": kind}) as observation:
            if name == "calculate":
                observation.attribute("tool.name", kind)
                observation.json_attribute("tool.parameters", state.get("inputs", {}))
            result = fn(state)
            observation.output(result)
            if "route" in result:
                observation.attribute("kplasma.route", result["route"])
            numeric = result.get("result") or result.get("answer") or {}
            status = numeric.get("resultStatus") or numeric.get("status")
            if status:
                observation.attribute("kplasma.result_status", status)
            if "candidates" in numeric:
                observation.attribute("kplasma.candidate_count", len(numeric["candidates"]))
            return result
    return observed

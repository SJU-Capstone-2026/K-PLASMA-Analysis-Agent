"""Authenticated, fenced worker transport. No provider/database credentials cross this boundary."""

import httpx
from . import tracing


class BackendError(RuntimeError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class BackendClient:
    def __init__(self, settings, transport=None):
        self.client = httpx.Client(
            base_url=settings.backend_url.rstrip("/") + "/internal/agent/",
            headers={"X-Agent-Token": settings.worker_token},
            timeout=30,
            transport=transport,
        )

    def call(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TransportError:
            raise BackendError("BACKEND_UNAVAILABLE", True) from None
        if not response.is_success:
            try:
                code = response.json().get("code", "BACKEND_REQUEST_FAILED")
            except ValueError:
                code = "BACKEND_REQUEST_FAILED"
            if not isinstance(code, str) or not code.replace("_", "").isupper():
                code = "BACKEND_REQUEST_FAILED"
            raise BackendError(code, response.status_code >= 500)
        return response.json()

    def claim(self, worker_id, supported_graph_versions=None):
        body = {"workerId": worker_id, "leaseSeconds": 60}
        if supported_graph_versions is not None:
            body["supportedGraphVersions"] = supported_graph_versions
        return self.call("POST", "claim", json=body)

    def bind(self, claim):
        return RequestBackend(self, claim)


class RequestBackend:
    def __init__(self, client, claim):
        from .progress import ProgressReporter

        self.client = client
        self.prefix = f"requests/{claim['request']['requestId']}/"
        self.fence = {k: claim[k] for k in ("claimGeneration", "requestRevision")}
        self.progress = ProgressReporter(self)
        self.graph_version = claim.get("request", {}).get("graphVersion", "v1")
        self.operation_kind = None
        self.public_stage = None

    def public_event(self, kind, payload, key):
        body = {**self.fence, "eventKey": key, "type": kind, "payload": payload}
        for attempt in range(2):
            try:
                return self.client.call("POST", self.prefix + "events", json=body, timeout=3.0)
            except BackendError as error:
                if not error.retryable or attempt:
                    raise

    def post(self, path, **fields):
        body = {**self.fence, **fields}
        if path == "heartbeat":
            return self.client.call("POST", self.prefix + path, json=body)
        # The opaque saver is already represented by readable node state spans.
        inputs = body if path != "checkpoint" else {"versions": fields.get("payload", {}).get("versions")}
        with tracing.span(f"backend.{path}", inputs=inputs) as observation:
            result = self.client.call("POST", self.prefix + path, json=body)
            observation.output(result)
            return result

    def stage(self, stage=None, **fields):
        result = self.post("heartbeat", stage=stage, leaseSeconds=60, **fields)
        self.operation_kind = fields.get("operationKind", self.operation_kind)
        if self.graph_version == "v1" and stage:
            code = {
                "select_tool": "PLAN", "guard": "PLAN_VALIDATE", "gather": "QUESTION_CHECK",
                "calculate": {"forward_lookup": "FORWARD_LOOKUP", "reverse_search": "REVERSE_SEARCH",
                              "compare_runs": "COMPARE_RUNS"}.get(self.operation_kind or "", "DERIVE"),
                "load_comparison_outputs": "COMPARE_OUTPUTS", "validate_result": "RESULT_VALIDATE",
                "generate_answer": "GENERAL_ANSWER", "validate_answer": "RESULT_VALIDATE",
                "present": "COMMIT", "commit": "COMMIT",
            }.get(stage)
            if code and (self.public_stage is None or self.public_stage[0] != code):
                if self.public_stage is not None:
                    previous, identity = self.public_stage
                    self.progress.activity(previous, "completed", identity=identity)
                identity = self.progress.activity(code)
                self.public_stage = (code, identity)
        return result

    def attempt(self, stage):
        return self.post("attempt", stage=stage, limit=4)

    def context(self, refs=None, *, reverse_query=None, forward_query=None, references_only=False):
        fields = {"requiredRunRefs": refs or []}
        if reverse_query is not None:
            fields["reverseQuery"] = reverse_query
        if forward_query is not None:
            fields["forwardQuery"] = forward_query
        if references_only:
            fields["referencesOnly"] = True
        return self.post("context", **fields)

    def decision_records(self):
        # The backend pins the first read in the request manifest; call after context().
        return self.post("decision-records")["records"]

    def comparison_outputs(self, refs, plots):
        return self.post("comparison-outputs", runRefs=refs, plotIds=plots)

    def checkpoint(self):
        with tracing.span("backend.checkpoint.load", inputs=self.fence) as observation:
            result = self.client.call("GET", self.prefix + "checkpoint", params=self.fence)["payload"]
            observation.output({"present": result is not None, "versions": (result or {}).get("versions")})
            return result

    def save(self, payload):
        return self.post("checkpoint", payload=payload)

    def needs_input(self, pending):
        return self.post("needs-input", pendingInput=pending)

    def finalize(self, answer):
        return self.post("finalize", answer=answer)

    def fail(self, code, partial=None):
        messages = {
            "MODEL_NOT_CONFIGURED": "OPENAI_API_KEY가 설정되지 않았습니다.",
            "MODEL_UNAVAILABLE": "모델 연결을 완료하지 못했습니다. 잠시 후 다시 질문해 주세요.",
            "MODEL_TIMEOUT": "모델 응답 대기 시간이 초과되었습니다. 잠시 후 다시 질문해 주세요.",
            "MODEL_CONNECTION": "모델에 연결하지 못했습니다. 연결 상태를 확인하고 다시 질문해 주세요.",
            "MODEL_RATE_LIMITED": "모델 API 요청 한도에 도달했습니다. 잠시 후 다시 질문해 주세요.",
            "MODEL_STREAM_ERROR": "모델 응답 스트림을 완료하지 못했습니다. 다시 질문해 주세요.",
            "MODEL_API_ERROR": "모델 API 요청을 완료하지 못했습니다. 오류 코드를 확인해 주세요.",
            "MODEL_OUTPUT_TRUNCATED": "모델 응답이 출력 길이 제한에 도달했습니다. 오류 코드를 확인해 주세요.",
            "MODEL_RESPONSE_INCOMPLETE": "모델이 미완료 응답을 반환했습니다. 오류 코드를 확인해 주세요.",
            "MODEL_RESPONSE_FAILED": "모델 공급자가 응답 생성을 실패로 종료했습니다. 오류 코드를 확인해 주세요.",
            "MODEL_CONTENT_FILTERED": "모델 응답이 콘텐츠 필터에 의해 중단되었습니다. 오류 코드를 확인해 주세요.",
            "MODEL_STREAM_INTERRUPTED": "모델 응답의 종료 신호를 받지 못했습니다. 다시 질문해 주세요.",
            "MODEL_ATTEMPT_LIMIT": "모델 처리 횟수 제한에 도달했습니다. 새 질문으로 시작해 주세요.",
            "RECOVERY_VERSION_MISMATCH": "저장된 작업의 실행 버전이 달라 안전하게 재개할 수 없습니다. 새 질문으로 시작해 주세요.",
        }
        return self.post(
            "fail",
            error={
                "code": code,
                "message": messages.get(
                    code, "모델 API 요청이 실패했습니다. 오류 코드를 확인해 주세요." if code.startswith("MODEL_HTTP_")
                    else "분석을 완료하지 못했습니다. 오류 코드와 조건을 확인해 주세요."
                ),
            },
            partialResult=partial,
            usedRunRefs=(partial or {}).get("usedRunRefs", []),
        )

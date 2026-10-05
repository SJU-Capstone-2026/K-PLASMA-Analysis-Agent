"""Authenticated, fenced worker transport. No provider/database credentials cross this boundary."""

import httpx


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

    def claim(self, worker_id):
        return self.call("POST", "claim", json={"workerId": worker_id, "leaseSeconds": 60})

    def bind(self, claim):
        return RequestBackend(self, claim)


class RequestBackend:
    def __init__(self, client, claim):
        self.client = client
        self.prefix = f"requests/{claim['request']['requestId']}/"
        self.fence = {k: claim[k] for k in ("claimGeneration", "requestRevision")}

    def post(self, path, **fields):
        return self.client.call("POST", self.prefix + path, json={**self.fence, **fields})

    def stage(self, stage=None, **fields):
        return self.post("heartbeat", stage=stage, leaseSeconds=60, **fields)

    def attempt(self, stage):
        return self.post("attempt", stage=stage, limit=4)

    def context(self, refs=None, *, reverse_query=None, references_only=False):
        fields = {"requiredRunRefs": refs or []}
        if reverse_query is not None:
            fields["reverseQuery"] = reverse_query
        if references_only:
            fields["referencesOnly"] = True
        return self.post("context", **fields)

    def checkpoint(self):
        return self.client.call("GET", self.prefix + "checkpoint", params=self.fence)["payload"]

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
            "MODEL_ATTEMPT_LIMIT": "모델 처리 횟수 제한에 도달했습니다. 새 질문으로 시작해 주세요.",
            "RECOVERY_VERSION_MISMATCH": "저장된 작업의 실행 버전이 달라 안전하게 재개할 수 없습니다. 새 질문으로 시작해 주세요.",
        }
        return self.post(
            "fail",
            error={
                "code": code,
                "message": messages.get(
                    code, "분석을 완료하지 못했습니다. 오류 코드와 조건을 확인해 주세요."
                ),
            },
            partialResult=partial,
            usedRunRefs=(partial or {}).get("usedRunRefs", []),
        )

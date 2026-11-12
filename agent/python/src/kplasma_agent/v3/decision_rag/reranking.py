"""Pinned local cross-encoder inference; only explicit download() uses the network.

The model jointly classifies a question/passage pair for relevance. Its raw logits
are neither calibrated probabilities nor proof that a passage entails an answer.
No project text leaves this process, and no model code is downloaded or executed.

Original model: https://huggingface.co/BAAI/bge-reranker-v2-m3
ONNX conversion: https://huggingface.co/onnx-community/bge-reranker-v2-m3-ONNX
"""
from __future__ import annotations

from collections import OrderedDict
import importlib.metadata
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any
import urllib.request

from .embedding import file_sha256, normalized_text

MODEL_ID = "onnx-community/bge-reranker-v2-m3-ONNX"
BASE_MODEL_ID = "BAAI/bge-reranker-v2-m3"
REVISION = "6f5ff65298512715a1e669753bc754d2bc8f367b"
MODEL_FILES = {
    "model.onnx": (
        "onnx/model_quantized.onnx",
        "912fc1215c2dbff6499700534bd8d31253af01573861abbfc43afd1fab6cce5d",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "8bf8afbfd11306bd872018c53bfdf2e160a56f8edbcf49933324404791c148d3",
    ),
}
MAX_TOKENS = 512
BATCH_SIZE = 4
CACHE_SIZE = 512


class RerankingError(ValueError):
    code = "RERANKING_UNAVAILABLE"


def _artifact_metadata() -> dict:
    return {"model": MODEL_ID, "baseModel": BASE_MODEL_ID, "revision": REVISION,
            "sha256": {name: digest for name, (_, digest) in MODEL_FILES.items()},
            "quantization": "int8", "scoreKind": "raw-relevance-logit"}


def download(directory: Path) -> dict:
    """Explicitly fetch only two public, revision-pinned, hash-checked artifacts.

    Existing files are never replaced. A failed transfer only removes the new
    temporary file created by this call, so retrying cannot load a partial model.
    No credentials, user questions, or passages are included in requests.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, (remote, expected) in MODEL_FILES.items():
        target = directory / name
        if target.exists():
            if not target.is_file() or file_sha256(target) != expected:
                raise RerankingError("기존 재순위 모델 파일의 해시가 다릅니다. 기존 파일은 변경하지 않았습니다.")
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=name + ".", suffix=".partial",
                                             delete=False) as output:
                temporary = Path(output.name)
                url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{remote}"
                request = urllib.request.Request(url, headers={"User-Agent": "kplasma-local-rag/0.1"})
                with urllib.request.urlopen(request, timeout=90) as response:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        output.write(chunk)
            if file_sha256(temporary) != expected:
                raise RerankingError("공개 재순위 모델 다운로드의 무결성 확인에 실패했습니다.")
            # On Windows rename refuses to overwrite an existing target.
            temporary.rename(target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return _artifact_metadata()


def _finite_logits(output: Any, count: int) -> list[float]:
    """Require exactly one finite relevance logit for every question/passage pair."""
    import numpy as np  # type: ignore[import-not-found]

    logits = np.asarray(output)
    if (logits.shape not in {(count,), (count, 1)}
            or not np.issubdtype(logits.dtype, np.number) or not np.isrealobj(logits)):
        raise RerankingError("재순위 모델에서 쌍마다 하나의 점수를 얻지 못했습니다.")
    values = [float(value) for value in logits.reshape(-1)]
    if not all(math.isfinite(value) for value in values):
        raise RerankingError("재순위 모델에서 유효한 유한 점수를 얻지 못했습니다.")
    return values


class LocalReranker:
    """Offline CPU scorer with bounded pair cache and serialized tokenizer use."""

    def __init__(self, directory: Path, *, threads: int = 4):
        # Integrity validation precedes loading; construction never fetches files.
        directory = Path(directory)
        for name, (_, expected) in MODEL_FILES.items():
            target = directory / name
            if not target.is_file() or file_sha256(target) != expected:
                raise RerankingError("로컬 재순위 모델이 없거나 해시가 다릅니다. download 명령을 먼저 실행하세요.")

        import numpy as np
        import onnxruntime as ort  # type: ignore[import-untyped, import-not-found]
        from tokenizers import Tokenizer  # type: ignore[import-not-found]

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(threads, os.cpu_count() or 1))
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS, strategy="only_second")
        pad = self.tokenizer.token_to_id("<pad>")
        if pad is None:
            raise RerankingError("재순위 tokenizer에 padding 토큰이 없습니다.")
        self.tokenizer.enable_padding(pad_id=pad, pad_token="<pad>")
        self._np = np
        self._lock = threading.RLock()
        self._cache: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._inputs = {}
        for entry in self.session.get_inputs():
            if entry.name not in {"input_ids", "attention_mask", "token_type_ids"}:
                raise RerankingError("재순위 모델에 지원하지 않는 입력이 있습니다.")
            dtype = {"tensor(int64)": np.int64, "tensor(int32)": np.int32}.get(entry.type)
            if dtype is None:
                raise RerankingError("재순위 모델의 입력 형식이 지원되지 않습니다.")
            self._inputs[entry.name] = dtype
        if not {"input_ids", "attention_mask"}.issubset(self._inputs):
            raise RerankingError("재순위 모델에 필수 입력이 없습니다.")
        self.metadata = {**_artifact_metadata(),
                         "modelSha256": MODEL_FILES["model.onnx"][1],
                         "tokenizerSha256": MODEL_FILES["tokenizer.json"][1],
                         "provider": "CPUExecutionProvider", "device": "cpu", "local": True,
                         "telemetry": False, "maxTokens": MAX_TOKENS, "batchSize": BATCH_SIZE,
                         "cacheSize": CACHE_SIZE, "truncation": "only_second",
                         "preprocess": "run-id-to-placeholder-v1",
                         "onnxruntime": ort.__version__,
                         "tokenizers": importlib.metadata.version("tokenizers"), "numpy": np.__version__}

    def score(self, question: str, texts, *, batch_size: int = BATCH_SIZE) -> list[float]:
        """Return raw finite logits in passage order, retaining all question tokens.

        Run identifiers are replaced on both sides. Scope must be enforced by
        the caller's metadata filter, rather than learned identifier matches.
        Oversized questions fail explicitly when only-second truncation cannot
        form a pair. No instructions contained in passages are executed.
        """
        if not isinstance(question, str) or isinstance(texts, (str, bytes)):
            raise RerankingError("재순위 입력은 질문 문자열과 문서 문자열 목록이어야 합니다.")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise RerankingError("재순위 batch_size는 양의 정수여야 합니다.")
        # A caller cannot accidentally raise memory use with an unbounded batch.
        batch_size = min(batch_size, BATCH_SIZE)
        texts = list(texts)
        if not all(isinstance(text, str) for text in texts):
            raise RerankingError("재순위 문서는 모두 문자열이어야 합니다.")
        if not texts:
            return []
        question = normalized_text(question)
        keys = [(question, normalized_text(text)) for text in texts]
        with self._lock:
            # Keep per-call results separately because more than CACHE_SIZE
            # passages may be scored without extending the persistent cache.
            results = {}
            missing = []
            for key in dict.fromkeys(keys):
                if key in self._cache:
                    results[key] = self._cache[key]
                    self._cache.move_to_end(key)
                else:
                    missing.append(key)
            for start in range(0, len(missing), batch_size):
                batch = missing[start:start + batch_size]
                try:
                    encoded = self.tokenizer.encode_batch(batch)
                except Exception as exc:
                    raise RerankingError("재순위 질문/문서를 512 토큰 쌍으로 변환하지 못했습니다.") from exc
                fields = {"input_ids": [entry.ids for entry in encoded],
                          "attention_mask": [entry.attention_mask for entry in encoded],
                          "token_type_ids": [entry.type_ids for entry in encoded]}
                inputs = {name: self._np.asarray(fields[name], dtype=dtype)
                          for name, dtype in self._inputs.items()}
                try:
                    output = self.session.run(None, inputs)[0]
                except Exception as exc:
                    raise RerankingError("로컬 재순위 모델 실행에 실패했습니다.") from exc
                values = _finite_logits(output, len(batch))
                for key, value in zip(batch, values, strict=True):
                    results[key] = value
                    self._cache[key] = value
                    self._cache.move_to_end(key)
                    while len(self._cache) > CACHE_SIZE:
                        self._cache.popitem(last=False)
            return [results[key] for key in keys]

    def describe(self) -> str:
        return json.dumps(self.metadata, ensure_ascii=False, sort_keys=True)

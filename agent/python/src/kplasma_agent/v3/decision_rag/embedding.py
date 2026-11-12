"""Pinned E5 ONNX inference. Only explicit download() performs network I/O.

Pooling and query/passage prefixes follow the original E5 model card:
https://huggingface.co/intfloat/multilingual-e5-small
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import urllib.request

MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_FILES = {
    "model.onnx": ("onnx/model_qint8_avx512_vnni.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    "tokenizer.json": ("onnx/tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
}


class EmbeddingError(ValueError):
    code = "EMBEDDING_UNAVAILABLE"


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def download(directory: Path) -> dict:
    """Fetch public weights only, without credentials or any project text."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, (remote, expected) in MODEL_FILES.items():
        target = directory / name
        if target.exists():
            if file_sha256(target) != expected:
                raise EmbeddingError("기존 모델 파일의 해시가 다릅니다. 기존 파일은 변경하지 않았습니다.")
            continue
        partial = directory / (name + ".partial")
        url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{remote}"
        request = urllib.request.Request(url, headers={"User-Agent": "kplasma-local-rag/0.1"})
        with urllib.request.urlopen(request, timeout=90) as response, partial.open("xb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                output.write(chunk)
        if file_sha256(partial) != expected:
            raise EmbeddingError("공개 모델 다운로드의 무결성 확인에 실패했습니다.")
        partial.rename(target)
    return {"model": MODEL_ID, "revision": REVISION, "sha256": {n: s for n, (_, s) in MODEL_FILES.items()}}


def normalized_text(text: str) -> str:
    # Identity is enforced by metadata scope, never by embedding similarity.
    return re.sub(r"RUN-[A-Z0-9-]+", "해당 Run", text).strip()


class LocalEncoder:
    def __init__(self, directory: Path, *, threads: int = 4):
        import numpy as np  # type: ignore[import-not-found]
        import onnxruntime as ort  # type: ignore[import-untyped, import-not-found]
        from tokenizers import Tokenizer  # type: ignore[import-not-found]

        ort.disable_telemetry_events()
        directory = Path(directory)
        for name, (_, expected) in MODEL_FILES.items():
            if not (directory / name).is_file() or file_sha256(directory / name) != expected:
                raise EmbeddingError("로컬 모델이 없거나 해시가 다릅니다. download 명령을 먼저 실행하세요.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(threads, os.cpu_count() or 1))
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        pad = self.tokenizer.token_to_id("<pad>")
        if pad is None:
            raise EmbeddingError("모델 tokenizer에 padding 토큰이 없습니다.")
        self.tokenizer.enable_padding(pad_id=pad, pad_token="<pad>")
        self._np = np
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], Any] = {}
        self.metadata = {"model": MODEL_ID, "revision": REVISION, "dimension": 384,
                         "modelSha256": MODEL_FILES["model.onnx"][1],
                         "tokenizerSha256": MODEL_FILES["tokenizer.json"][1],
                         "provider": "CPUExecutionProvider", "device": "cpu", "local": True, "telemetry": False,
                         "normalization": "masked-mean-pool+l2", "maxTokens": 512,
                         "preprocess": "run-id-to-placeholder-v1", "prefixes": ["query: ", "passage: "],
                         "onnxruntime": ort.__version__, "tokenizers": importlib.metadata.version("tokenizers"),
                         "numpy": np.__version__}

    def encode(self, texts, *, kind="query", batch_size=12):
        if kind not in {"query", "passage"}:
            raise EmbeddingError("Unknown embedding input kind")
        np = self._np
        texts = list(texts)
        keys = [(kind, normalized_text(text)) for text in texts]
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        with self._lock:
            missing = list(dict.fromkeys(key for key in keys if key not in self._cache))
            for start in range(0, len(missing), batch_size):
                batch = missing[start:start + batch_size]
                encoded = self.tokenizer.encode_batch([f"{kind}: {text}" for _, text in batch])
                inputs = {"input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                          "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                          "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64)}
                allowed = {i.name for i in self.session.get_inputs()}
                output = self.session.run(None, {k: v for k, v in inputs.items() if k in allowed})[0]
                mask = inputs["attention_mask"][..., None].astype(np.float32)
                pooled = (output * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
                vectors = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
                if not np.isfinite(vectors).all() or vectors.shape != (len(batch), 384):
                    raise EmbeddingError("모델에서 유효한 임베딩을 얻지 못했습니다.")
                for key, vector in zip(batch, vectors, strict=True):
                    self._cache[key] = vector.astype(np.float32)
            return np.asarray([self._cache[key] for key in keys], dtype=np.float32)

    def describe(self) -> str:
        return json.dumps(self.metadata, ensure_ascii=False, sort_keys=True)

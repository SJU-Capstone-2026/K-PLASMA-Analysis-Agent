"""Candidate encoders with the LocalEncoder interface, for offline comparison only.

Files are read from .local/models/<dir>; their SHA256 is reported in metadata, not trusted from the path.
e5-small and ko-sroberta use the same specs as the product (decision_rag.embedding).
"""
import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from kplasma_agent.v3.decision_rag.embedding import normalized_text

SPECS = {
    "e5-small": {"dir": "multilingual-e5-small", "model": "intfloat/multilingual-e5-small",
                 "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
                 "prefix": ("query: ", "passage: "), "max": 512, "pad": "<pad>"},
    "e5-base": {"dir": "multilingual-e5-base", "model": "intfloat/multilingual-e5-base",
                "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
                "prefix": ("query: ", "passage: "), "max": 512, "pad": "<pad>"},
    "ko-sroberta": {"dir": "ko-sroberta-multitask", "model": "jhgan/ko-sroberta-multitask",
                    "revision": "8fca7c9c98c26599be0e14b9916b11a756a26f19",
                    "prefix": ("", ""), "max": 128, "pad": "[PAD]"},
}


class CandidateEncoder:
    def __init__(self, name, root=".local/models", threads=4):
        spec = SPECS[name]
        directory = Path(root) / spec["dir"]
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tok.enable_truncation(max_length=spec["max"])
        pad = self.tok.token_to_id(spec["pad"])
        if pad is None:
            raise ValueError(f"tokenizer has no {spec['pad']} token")
        self.tok.enable_padding(pad_id=pad, pad_token=spec["pad"])
        self.spec, self.allowed = spec, {i.name for i in self.session.get_inputs()}
        self._cache = {}
        self._lock = threading.RLock()
        self.encode_seconds = 0.0
        self.dim = self._run(["dimension probe"], "query").shape[1]
        self.metadata = {"model": spec["model"], "revision": spec["revision"], "dimension": self.dim,
                         "modelSha256": hashlib.sha256((directory / "model.onnx").read_bytes()).hexdigest(),
                         "maxTokens": spec["max"], "prefixes": list(spec["prefix"]),
                         "normalization": "masked-mean-pool+l2", "local": True}

    def _run(self, texts, kind):
        prefix = self.spec["prefix"][0 if kind == "query" else 1]
        encoded = self.tok.encode_batch([prefix + text for text in texts])
        inputs = {"input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                  "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                  "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64)}
        output = self.session.run(None, {k: v for k, v in inputs.items() if k in self.allowed})[0]
        mask = inputs["attention_mask"][..., None].astype(np.float32)
        pooled = (output * mask).sum(1) / np.maximum(mask.sum(1), 1)
        return (pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)).astype(np.float32)

    def encode(self, texts, *, kind="query", batch_size=12):
        keys = [(kind, normalized_text(text)) for text in texts]
        if not keys:
            return np.empty((0, self.dim), dtype=np.float32)
        with self._lock:
            missing = list(dict.fromkeys(key for key in keys if key not in self._cache))
            start = time.perf_counter()
            for index in range(0, len(missing), batch_size):
                batch = missing[index:index + batch_size]
                for key, vector in zip(batch, self._run([text for _, text in batch], kind), strict=True):
                    self._cache[key] = vector
            self.encode_seconds += time.perf_counter() - start
            return np.asarray([self._cache[key] for key in keys], dtype=np.float32)

    def describe(self):
        return json.dumps(self.metadata, sort_keys=True)

"""Pinned d1 loaders: BF16 or affine8 Linear layers with a dense BF16 readout."""

import hashlib
import json
from pathlib import Path
import re
import struct


FORMAT = "mlx-affine8-g64-linear-bf16-embedding-v1"
Q8_SPEC = {"format": FORMAT, "mode": "affine", "bits": 8, "group_size": 64,
           "embedding_dtype": "bfloat16"}
RELEASE_PREFIX = "model.language_model."
_LINEAR_PATH = re.compile(
    r"model\.layers\.\d+\.(?:feed_forward\.w[123]|"
    r"self_attn\.(?:q_proj|k_proj|v_proj|o_proj|gate_proj)|conv\.(?:in_proj|out_proj))"
)


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def quantization_spec(paths):
    return validate_quantization({**Q8_SPEC, "linear_paths": sorted(paths)})


def validate_quantization(value):
    if (not isinstance(value, dict) or set(value) != {*Q8_SPEC, "linear_paths"}
            or any(type(value.get(k)) is not type(v) or value[k] != v for k, v in Q8_SPEC.items())):
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    paths = value["linear_paths"]
    if (not isinstance(paths, list) or not paths
            or any(not isinstance(p, str) or not _LINEAR_PATH.fullmatch(p) for p in paths)
            or paths != sorted(set(paths))):
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    return value


def linear_paths(model, linear_type):
    return sorted(path for path, layer in model.named_modules()
                  if isinstance(layer, linear_type) and len(layer.weight.shape) == 2
                  and layer.weight.shape[-1] % Q8_SPEC["group_size"] == 0)


def verify_manifest(path):
    """Verify local source provenance before any tensor is loaded or output is written."""
    path = Path(path).resolve(strict=True)
    try:
        manifest = json.loads((path / "kplasma-manifest.json").read_text())
        files = manifest["files"]
        if (manifest["schema_version"] != 1 or manifest["model"] != "LiquidAI/d1-2B"
                or not isinstance(manifest["revision"], str) or not manifest["revision"]
                or not isinstance(files, dict)
                or not {"config.json", "tokenizer.json", "calibration.json"} <= set(files)):
            raise ValueError
        actual_weights = {f.name for f in path.glob("model*.safetensors")}
        if not actual_weights or not actual_weights <= set(files):
            raise ValueError
        for name, digest in files.items():
            if (not isinstance(name, str) or Path(name).name != name or name in {".", ".."}
                    or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                raise ValueError
            file = path / name
            if file.resolve(strict=True).parent != path or file_hash(file) != digest:
                raise ValueError
        return manifest
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError("LOCAL_MODEL_ARTIFACT_MISMATCH") from None


def _headers(path):
    headers = {}
    for file in sorted(path.glob("model*.safetensors")):
        with file.open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            if not 1 <= size <= min(16 * 1024**2, file.stat().st_size - 8):
                raise ValueError
            data = json.loads(handle.read(size))
        for name, meta in data.items():
            if name == "__metadata__":
                continue
            if name in headers or not name.startswith(RELEASE_PREFIX) or not isinstance(meta, dict):
                raise ValueError
            headers[name] = meta
    if not headers:
        raise ValueError
    return headers


def validate_q8_folder(path):
    """Check the compact layout from headers only; never materialize model tensors."""
    path = Path(path)
    try:
        config = json.loads((path / "config.json").read_text())
        spec = validate_quantization(config["kplasma_quantization"])
        manifest = json.loads((path / "kplasma-manifest.json").read_text())
        if manifest.get("quantization") != spec or manifest.get("dtype") != "affine8-bf16-embedding":
            raise ValueError
        headers = _headers(path)
        embedding = headers[RELEASE_PREFIX + "embed_tokens.weight"]
        if embedding["dtype"] != "BF16" or embedding["shape"] != [
            config["text_config"]["vocab_size"], config["text_config"]["hidden_size"]
        ]:
            raise ValueError
        quantized: set[str] = set()
        for module in spec["linear_paths"]:
            name = RELEASE_PREFIX + module.removeprefix("model.")
            weight, scales, biases = (headers[name + suffix] for suffix in (".weight", ".scales", ".biases"))
            shape = weight["shape"]
            if (weight["dtype"] != "U32" or len(shape) != 2
                    or any(type(n) is not int or n <= 0 for n in shape)
                    or shape[1] % 16 or scales["dtype"] != "BF16" or biases["dtype"] != "BF16"
                    or scales["shape"] != [shape[0], shape[1] // 16]
                    or biases["shape"] != scales["shape"]):
                raise ValueError
            quantized.update(name + suffix for suffix in (".weight", ".scales", ".biases"))
        if any(meta["dtype"] != "BF16" for name, meta in headers.items() if name not in quantized):
            raise ValueError
        return spec
    except (OSError, KeyError, TypeError, ValueError, struct.error):
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID") from None


def load_backend(path, precision, max_input_tokens):
    if precision not in {"bf16", "q8"} or type(max_input_tokens) is not int or not 1 <= max_input_tokens <= 16000:
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    path = Path(path).resolve(strict=True)
    if precision == "bf16":
        from mlx_decision.models.d1lfm3.model import load

        return load(path, max_input_tokens=max_input_tokens)
    spec = validate_q8_folder(path)
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_decision.backend import Capabilities
    from mlx_decision.backbones.lfm3.language import Model
    from mlx_decision.backbones.lfm3.vl_config import TextConfig
    from mlx_decision.models.d1lfm3.config import settings
    from mlx_decision.models.d1lfm3.model import D1Lfm3Backend
    from tokenizers import Tokenizer

    config = json.loads((path / "config.json").read_text())
    model = Model(TextConfig.from_dict(config["text_config"]))
    paths = linear_paths(model, nn.Linear)
    if paths != spec["linear_paths"]:
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    targets = set(paths)
    # Keep tied token/output embeddings dense: the pinned official readout indexes their rows.
    nn.quantize(model, bits=8, group_size=64, mode="affine",
                class_predicate=lambda name, layer: name in targets and isinstance(layer, nn.Linear))
    tensors = {}
    for file in sorted(path.glob("model*.safetensors")):
        tensors.update(mx.load(str(file)))
    model.load_weights(list(model.sanitize(tensors).items()), strict=True)
    model.eval()
    mx.eval(model.parameters())
    if model.model.embed_tokens.weight.dtype != mx.bfloat16:
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    backend = D1Lfm3Backend(path.name, model, Tokenizer.from_file(str(path / "tokenizer.json")),
                           settings(path), Capabilities(max_input_tokens=max_input_tokens), path)
    backend.precision = "8-bit-linear/bfloat16-embedding"
    return backend

"""CPU-only checks for the local affine8 artifact and conversion boundaries."""

import hashlib
import importlib
import json
import struct
import sys
from types import ModuleType, SimpleNamespace

import pytest


MODULE = "runtimes.d1_mlx.weights"
LINEAR = "model.layers.0.feed_forward.w1"
RELEASE = "model.language_model.layers.0.feed_forward.w1"


def weights():
    return importlib.import_module(MODULE)


def save_tensors(path, tensors):
    header, data = {}, bytearray()
    widths = {"BF16": 2, "U32": 4}
    for name, (dtype, shape) in tensors.items():
        count = 1
        for n in shape:
            count *= n
        start = len(data)
        data.extend(b"\0" * (count * widths[dtype]))
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [start, len(data)]}
    encoded = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + data)


def write_manifest(path, *, dtype="bfloat16", quantization=None):
    data = {"schema_version": 1, "model": "LiquidAI/d1-2B", "revision": "artificial-revision",
            "dtype": dtype, "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                      for f in sorted(path.iterdir()) if f.is_file()}}
    if quantization is not None:
        data["quantization"] = quantization
    (path / "kplasma-manifest.json").write_text(json.dumps(data))
    return data


def folder(path, *, q8=False):
    path.mkdir()
    spec = weights().quantization_spec([LINEAR])
    config = {"text_config": {"hidden_size": 64, "vocab_size": 2}}
    if q8:
        config["kplasma_quantization"] = spec
    (path / "config.json").write_text(json.dumps(config))
    (path / "tokenizer.json").write_text('{"artificial": true}')
    (path / "calibration.json").write_text('{"default": 1.2}')
    tensors = {"model.language_model.embed_tokens.weight": ("BF16", [2, 64])}
    if q8:
        tensors.update({RELEASE + ".weight": ("U32", [2, 16]),
                        RELEASE + ".scales": ("BF16", [2, 1]),
                        RELEASE + ".biases": ("BF16", [2, 1])})
    else:
        tensors[RELEASE + ".weight"] = ("BF16", [2, 64])
    save_tensors(path / "model.safetensors", tensors)
    write_manifest(path, dtype="affine8-bf16-embedding" if q8 else "bfloat16",
                   quantization=spec if q8 else None)
    return spec


def test_q8_metadata_and_dense_embedding_are_checked_without_importing_mlx(tmp_path):
    spec = folder(tmp_path / "q8", q8=True)
    assert weights().validate_q8_folder(tmp_path / "q8") == spec


@pytest.mark.parametrize("field,value", [("bits", 4), ("bits", True), ("group_size", 32),
                                        ("mode", "mxfp8"), ("embedding_dtype", "uint32")])
def test_other_precisions_and_changed_readout_format_are_refused(field, value):
    spec = weights().quantization_spec([LINEAR])
    spec[field] = value
    with pytest.raises(ValueError, match="LOCAL_D1_QUANTIZATION_INVALID"):
        weights().validate_quantization(spec)


@pytest.mark.parametrize("paths", [[], [LINEAR, LINEAR], ["model.embed_tokens"], ["../layers"]])
def test_invalid_or_embedding_quantization_targets_are_refused(paths):
    spec = {**weights().quantization_spec([LINEAR]), "linear_paths": paths}
    with pytest.raises(ValueError, match="LOCAL_D1_QUANTIZATION_INVALID"):
        weights().validate_quantization(spec)


def test_quantization_config_must_match_the_manifest(tmp_path):
    path = tmp_path / "q8"
    folder(path, q8=True)
    data = json.loads((path / "kplasma-manifest.json").read_text())
    data["quantization"]["bits"] = 4
    (path / "kplasma-manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="LOCAL_D1_QUANTIZATION_INVALID"):
        weights().validate_q8_folder(path)


def test_q8_requires_packed_linear_weights_and_bf16_tied_readout(tmp_path):
    path = tmp_path / "q8"
    spec = folder(path, q8=True)
    save_tensors(path / "model.safetensors", {
        "model.language_model.embed_tokens.weight": ("U32", [2, 16]),
        RELEASE + ".weight": ("U32", [2, 16]),
        RELEASE + ".scales": ("BF16", [2, 1]),
        RELEASE + ".biases": ("BF16", [2, 1]),
    })
    write_manifest(path, dtype="affine8-bf16-embedding", quantization=spec)
    with pytest.raises(ValueError, match="LOCAL_D1_QUANTIZATION_INVALID"):
        weights().validate_q8_folder(path)


def test_source_manifest_tampering_and_outside_files_are_refused(tmp_path):
    path = tmp_path / "source"
    folder(path)
    (path / "calibration.json").write_text('{"default": 9}')
    with pytest.raises(ValueError, match="LOCAL_MODEL_ARTIFACT_MISMATCH"):
        weights().verify_manifest(path)
    data = json.loads((path / "kplasma-manifest.json").read_text())
    data["files"] = {"../outside": "0" * 64}
    (path / "kplasma-manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="LOCAL_MODEL_ARTIFACT_MISMATCH"):
        weights().verify_manifest(path)


def test_invalid_precision_and_remote_source_fail_before_gpu_import(tmp_path):
    with pytest.raises(ValueError, match="LOCAL_D1_QUANTIZATION_INVALID"):
        weights().load_backend(tmp_path, "q4", 16000)
    converter = importlib.import_module("runtimes.d1_mlx.convert")
    with pytest.raises(ValueError, match="LOCAL_MODEL_PATH_REQUIRED"):
        converter.convert_model("https://outside.invalid/model", tmp_path / "result")


def test_converter_preserves_source_and_atomically_writes_a_local_derivative(tmp_path, monkeypatch):
    source = tmp_path / "source"
    folder(source)
    before = {f.name: f.read_bytes() for f in source.iterdir()}
    converter = importlib.import_module("runtimes.d1_mlx.convert")

    def synthetic_conversion(_source, target):
        staged = tmp_path / "synthetic"
        spec = folder(staged, q8=True)
        (target / "model.safetensors").write_bytes((staged / "model.safetensors").read_bytes())
        return spec

    monkeypatch.setattr(converter, "_convert_tensors", synthetic_conversion)
    output = tmp_path / "result"
    result = converter.convert_model(source, output)
    assert result == output.resolve()
    assert {f.name: f.read_bytes() for f in source.iterdir()} == before
    for name in ("tokenizer.json", "calibration.json"):
        assert (output / name).read_bytes() == before[name]
    manifest = weights().verify_manifest(output)
    assert manifest["revision"] == "artificial-revision"
    assert manifest["source_manifest_sha256"] == hashlib.sha256(before["kplasma-manifest.json"]).hexdigest()
    assert manifest["quantization"] == weights().validate_q8_folder(output)


def test_failed_conversion_never_overwrites_or_leaves_a_partial_model(tmp_path, monkeypatch):
    source = tmp_path / "source"
    folder(source)
    converter = importlib.import_module("runtimes.d1_mlx.convert")
    output = tmp_path / "result"
    output.mkdir()
    (output / "keep").write_text("existing")
    with pytest.raises(FileExistsError):
        converter.convert_model(source, output)
    assert (output / "keep").read_text() == "existing"
    destination = tmp_path / "new"

    def fail(_source, target):
        (target / "model.safetensors").write_bytes(b"unfinished")
        raise RuntimeError("conversion interrupted")

    monkeypatch.setattr(converter, "_convert_tensors", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        converter.convert_model(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".new.*.partial"))


def test_bf16_loader_keeps_the_pinned_official_path(tmp_path, monkeypatch):
    marker = object()
    calls = []
    module = ModuleType("mlx_decision.models.d1lfm3.model")

    def load(path, *, max_input_tokens):
        calls.append((path, max_input_tokens))
        return marker

    module.load = load
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert weights().load_backend(tmp_path, "bf16", 16000) is marker
    assert calls == [(tmp_path.resolve(), 16000)]


def test_q8_loader_quantizes_only_linear_layers_before_strict_tensor_loading(tmp_path, monkeypatch):
    path = tmp_path / "q8"
    folder(path, q8=True)
    calls = []

    class Linear:
        weight = SimpleNamespace(shape=(2, 64))

    class Model:
        def __init__(self, config):
            self.config = config
            self.model = SimpleNamespace(embed_tokens=SimpleNamespace(weight=SimpleNamespace(dtype="bf16")))

        def named_modules(self):
            return [(LINEAR, Linear()), ("model.embed_tokens", self.model.embed_tokens)]

        def sanitize(self, data):
            return data

        def load_weights(self, data, *, strict):
            assert calls == ["quantize", "load"] and strict is True
            calls.append("strict_weights")

        def eval(self):
            calls.append("eval")

        def parameters(self):
            return {"fake": "params"}

    def quantize(model, *, bits, group_size, mode, class_predicate):
        assert (bits, group_size, mode) == (8, 64, "affine")
        assert [name for name, layer in model.named_modules() if class_predicate(name, layer)] == [LINEAR]
        calls.append("quantize")

    def load_tensors(file):
        assert calls == ["quantize"]
        calls.append("load")
        return {"artificial.weight": "packed"}

    dependencies = {
        "mlx": {},
        "mlx.core": {"bfloat16": "bf16", "load": load_tensors,
                     "eval": lambda value: calls.append("materialize")},
        "mlx.nn": {"Linear": Linear, "quantize": quantize},
        "mlx_decision.backend": {"Capabilities": lambda **kw: SimpleNamespace(**kw)},
        "mlx_decision.backbones.lfm3.language": {"Model": Model},
        "mlx_decision.backbones.lfm3.vl_config": {"TextConfig": SimpleNamespace(from_dict=lambda value: value)},
        "mlx_decision.models.d1lfm3.config": {"settings": lambda _: "official-calibration"},
        "mlx_decision.models.d1lfm3.model": {
            "D1Lfm3Backend": lambda *args: SimpleNamespace(args=args)},
        "tokenizers": {"Tokenizer": SimpleNamespace(from_file=lambda _: "original-tokenizer")},
    }
    for name, values in dependencies.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules["mlx"].core = sys.modules["mlx.core"]
    sys.modules["mlx"].nn = sys.modules["mlx.nn"]
    backend = weights().load_backend(path, "q8", 16000)
    assert calls == ["quantize", "load", "strict_weights", "eval", "materialize"]
    assert backend.args[2] == "original-tokenizer" and backend.args[3] == "official-calibration"
    assert backend.args[4].max_input_tokens == 16000
    assert backend.precision == "8-bit-linear/bfloat16-embedding"

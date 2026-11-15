"""Create a local d1 affine8 derivative; no downloads or changes to the BF16 source."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

if __package__:
    from .weights import file_hash, linear_paths, quantization_spec, validate_q8_folder, verify_manifest
else:
    from weights import file_hash, linear_paths, quantization_spec, validate_q8_folder, verify_manifest


def _convert_tensors(source, target):
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_flatten
    from mlx_decision.backbones.lfm3.load import load_text_model

    if not mx.metal.is_available():
        raise ValueError("LOCAL_D1_MLX_RUNTIME_MISMATCH")
    mx.set_default_device(mx.gpu)
    model = load_text_model(source)
    spec = quantization_spec(linear_paths(model, nn.Linear))
    targets = set(spec["linear_paths"])
    nn.quantize(model, bits=8, group_size=64, mode="affine",
                class_predicate=lambda name, layer: name in targets and isinstance(layer, nn.Linear))
    if model.model.embed_tokens.weight.dtype != mx.bfloat16:
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    tensors = {}
    for name, value in tree_flatten(model.parameters()):
        if not name.startswith("model."):
            raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
        if name.endswith("conv.conv.weight"):
            value = value.transpose(0, 2, 1)
        tensors["model.language_model." + name.removeprefix("model.")] = value
    mx.eval(tensors)
    mx.save_safetensors(str(target / "model.safetensors"), tensors)
    return spec


def convert_model(source, output):
    if "://" in str(source):
        raise ValueError("LOCAL_MODEL_PATH_REQUIRED")
    source = Path(source).expanduser().resolve(strict=True)
    output = Path(output).expanduser().absolute()
    if not source.is_dir() or output.resolve().is_relative_to(source):
        raise ValueError("LOCAL_MODEL_PATH_REQUIRED")
    if os.path.lexists(output):
        raise FileExistsError("output folder already exists")
    manifest = verify_manifest(source)
    if manifest.get("dtype") != "bfloat16":
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    config = json.loads((source / "config.json").read_text())
    if "kplasma_quantization" in config or "quantization" in config:
        raise ValueError("LOCAL_D1_QUANTIZATION_INVALID")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + output.name + ".", suffix=".partial", dir=output.parent))
    try:
        spec = _convert_tensors(source, temporary)
        for name in manifest["files"]:
            if name != "config.json" and not name.startswith("model"):
                shutil.copyfile(source / name, temporary / name)
        (temporary / "config.json").write_text(json.dumps({**config, "kplasma_quantization": spec},
                                                        ensure_ascii=False, indent=2) + "\n")
        files = {f.name: file_hash(f) for f in sorted(temporary.iterdir()) if f.is_file()}
        converted = {"schema_version": 1, "model": "LiquidAI/d1-2B", "revision": manifest["revision"],
                     "dtype": "affine8-bf16-embedding", "quantization": spec,
                     "source_manifest_sha256": file_hash(source / "kplasma-manifest.json"),
                     "files": files}
        (temporary / "kplasma-manifest.json").write_text(json.dumps(converted, indent=2) + "\n")
        validate_q8_folder(temporary)
        if os.path.lexists(output):
            raise FileExistsError("output folder already exists")
        temporary.rename(output)
        return output.resolve()
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = convert_model(args.source, args.output)
    print(json.dumps({"model_path": str(result), "manifest_sha256": file_hash(result / "kplasma-manifest.json")}))


if __name__ == "__main__":
    main()

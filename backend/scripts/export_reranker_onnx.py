"""Export a torch-only cross-encoder to a graph-optimized ONNX file, in place.

Generates an ONNX export for models that publish none (such as the default
BAAI/bge-reranker-v2-m3) with torch.onnx.export plus onnxruntime's own
transformer optimizer, written INSIDE the snapshot as onnx/model_O3.onnx,
which is exactly where the adapter's priority path looks. No optimum
involved: every optimum flavour pins a transformers line carrying fixed
CVEs, and torch + onnxruntime are already runtime dependencies.

MEASURED VERDICT, and why the Dockerfile does NOT run this by default: on
ARM the exported fp32-O2 graph is SLOWER than the torch forward pass for
this 568M model (2854 ms vs 1958 ms per 40 pairs on an M4 Max) -- published
ONNX speedups are x86 numbers. Use this tool when deploying on x86, and
measure there; on ARM, keep the torch path the adapter picks by itself.

Run with the export-only deps supplied ephemerally (they never enter the
runtime image):

    uv run --with onnx --with onnxscript python scripts/export_reranker_onnx.py <model-id>

The export is verified before it is kept: torch and ONNX logits must agree
on a reference pair, so a silent export bug fails the build, never retrieval.

Usage: python scripts/export_reranker_onnx.py <model-id>
"""

import sys
import tempfile
from pathlib import Path

import numpy
import torch
from huggingface_hub import snapshot_download
from onnxruntime import InferenceSession
from onnxruntime.transformers import optimizer as ort_optimizer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REFERENCE_PAIR = (
    "Quelles obligations de securite selon la nLPD ?",
    "Les responsables du traitement doivent assurer une securite adequate des donnees.",
)
MAX_LOGIT_DELTA = 1e-3


def main(model_id: str) -> None:
    snapshot = Path(
        snapshot_download(
            model_id,
            allow_patterns=[
                "config.json",
                "tokenizer*",
                "special_tokens_map.json",
                "sentencepiece*",
                "*.safetensors",
            ],
        )
    )
    target = snapshot / "onnx" / "model_O3.onnx"
    if target.is_file():
        print(f"{model_id}: ONNX export already present, nothing to do")
        return

    tokenizer = AutoTokenizer.from_pretrained(snapshot)
    model = AutoModelForSequenceClassification.from_pretrained(snapshot)
    model.eval()
    encoded = tokenizer([REFERENCE_PAIR[0]], [REFERENCE_PAIR[1]], padding=True, return_tensors="pt")
    with torch.no_grad():
        torch_logit = float(model(**encoded).logits[0][0])

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "model.onnx"
        # The fp32 weights exceed protobuf's 2 GB single-file cap, so both the
        # raw export and the optimized graph use ONNX external data (the
        # .onnx graph plus a sibling weights file; InferenceSession resolves
        # the pair transparently from the same directory).
        program = torch.onnx.export(
            model,
            (encoded["input_ids"], encoded["attention_mask"]),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_shapes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
            },
            dynamo=True,
        )
        assert program is not None
        program.save(str(raw), external_data=True)
        optimized = ort_optimizer.optimize_model(
            str(raw),
            model_type="bert",
            num_heads=model.config.num_attention_heads,
            hidden_size=model.config.hidden_size,
            opt_level=2,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        optimized.save_model_to_file(
            str(target), use_external_data_format=True, all_tensors_to_one_file=True
        )

    session = InferenceSession(str(target), providers=["CPUExecutionProvider"])
    input_names = {i.name for i in session.get_inputs()}
    onnx_inputs = {name: array.numpy() for name, array in encoded.items() if name in input_names}
    onnx_logit = float(session.run(None, onnx_inputs)[0][0][0])
    delta = abs(onnx_logit - torch_logit)
    if delta > MAX_LOGIT_DELTA or not numpy.isfinite(onnx_logit):
        target.unlink()
        raise SystemExit(
            f"export rejected: torch={torch_logit:.6f} onnx={onnx_logit:.6f} delta={delta:.6f}"
        )
    print(f"{model_id}: exported ({delta=:.2e}); pruning the torch weights from the layer")
    # The runtime loads the ONNX file only; dropping the torch blobs keeps the
    # image from paying for the weights twice.
    for link in snapshot.glob("*.safetensors"):
        blob = link.resolve()
        link.unlink()
        if blob.exists():
            blob.unlink()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BAAI/bge-reranker-v2-m3")

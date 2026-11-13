"""Downloads the embedding model once, to bundle it with the installer (so the app works offline from the start).

    python packaging/fetch_model.py            -> dist/model/multilingual-e5-small
"""
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL = "intfloat/multilingual-e5-small"
OUT = Path(__file__).resolve().parent.parent / "dist" / "model" / "multilingual-e5-small"

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    # only what sentence-transformers needs: no ONNX/OpenVINO copies, no second weights format
    snapshot_download(MODEL, local_dir=OUT, allow_patterns=[
        "*.json", "*.txt", "model.safetensors", "sentencepiece.bpe.model", "1_Pooling/*", "modules.json"])
    print(f"model in {OUT}")
    sys.exit(0)

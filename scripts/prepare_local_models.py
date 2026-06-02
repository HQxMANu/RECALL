from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


OPENCLIP_REPO_ID = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
OPENCLIP_CHECKPOINT = "open_clip_model.safetensors"
OPENCLIP_DIR = Path("openclip") / "ViT-B-32"
BGE_REPO_ID = "BAAI/bge-small-en-v1.5"
BGE_DIR = Path("bge-small-en-v1.5")


def prepare_openclip_model(model_root: Path) -> Path:
    target_dir = model_root / OPENCLIP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(
        hf_hub_download(
            repo_id=OPENCLIP_REPO_ID,
            filename=OPENCLIP_CHECKPOINT,
            local_dir=target_dir,
        )
    )
    shutil.rmtree(target_dir / ".cache", ignore_errors=True)
    return checkpoint_path


def prepare_bge_model(model_root: Path) -> Path:
    target_dir = model_root / BGE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=BGE_REPO_ID,
        local_dir=target_dir,
        allow_patterns=["*.json", "*.txt", "*.safetensors", "*.bin"],
    )
    shutil.rmtree(target_dir / ".cache", ignore_errors=True)
    duplicate_bin = target_dir / "pytorch_model.bin"
    if duplicate_bin.exists() and (target_dir / "model.safetensors").exists():
        duplicate_bin.unlink()
    return target_dir


def write_manifest(model_root: Path, openclip_path: Path, bge_dir: Path) -> None:
    manifest = {
        "modelRoot": str(model_root),
        "coreModels": {
            "openclip": {
                "repoId": OPENCLIP_REPO_ID,
                "checkpoint": str(openclip_path),
            },
            "bgeSmall": {
                "repoId": BGE_REPO_ID,
                "directory": str(bge_dir),
            },
        },
    }
    (model_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare local Recall model assets for offline startup.")
    parser.add_argument(
        "--model-root",
        type=Path,
        default=Path("python") / "models",
        help="Directory where Recall's local model assets should be stored.",
    )
    args = parser.parse_args()

    model_root = args.model_root.expanduser().resolve()
    model_root.mkdir(parents=True, exist_ok=True)

    openclip_path = prepare_openclip_model(model_root)
    bge_dir = prepare_bge_model(model_root)
    write_manifest(model_root, openclip_path, bge_dir)

    print(f"Prepared Recall core models in {model_root}")
    print(f"  - OpenCLIP checkpoint: {openclip_path}")
    print(f"  - BGE model dir: {bge_dir}")


if __name__ == "__main__":
    main()

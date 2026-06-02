from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
OPENCLIP_MODEL_DIR = Path("openclip") / "ViT-B-32"
BGE_MODEL_DIR = Path("bge-small-en-v1.5")


@dataclass(slots=True)
class EmbeddingHealth:
    engine_name: str
    model_name: str
    degraded: bool
    dimension: int


class HashFallbackEmbedder:
    engine_name = "hash-fallback"
    model_name = "hash-fallback-v1"
    degraded = True
    dimension = 384

    def embed_text(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        tokens = TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for index in range(0, min(len(digest), self.dimension // 4)):
                vector[(digest[index] + index) % self.dimension] += 1.0
        norm = np.linalg.norm(vector)
        return vector if norm == 0 else vector / norm


class BaseImageEmbedder(HashFallbackEmbedder):
    def embed_image(
        self,
        image_path: Path,
        hint_text: str = "",
        image: Image.Image | None = None,
    ) -> np.ndarray:
        source = image if image is not None else Image.open(image_path)
        try:
            prepared = source.convert("RGB").resize((24, 24))
            array = np.asarray(prepared, dtype=np.float32).reshape(-1, 3)
        finally:
            if image is None:
                source.close()
        color_summary = array.mean(axis=0)
        color_tokens = (
            f"r{round(color_summary[0])} g{round(color_summary[1])} b{round(color_summary[2])}"
        )
        return self.embed_text(f"{image_path.name} {hint_text} {color_tokens}")


class OpenClipImageEmbedder(BaseImageEmbedder):
    engine_name = "openclip"
    model_name = "ViT-B-32"
    degraded = False
    dimension = 512
    repo_id = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    checkpoint_name = "open_clip_model.safetensors"

    def __init__(self) -> None:
        import open_clip  # type: ignore
        import torch  # type: ignore

        self._torch = torch
        self._device = "cpu"
        checkpoint_path = resolve_openclip_checkpoint(self.checkpoint_name)
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            self.model_name,
            pretrained=str(checkpoint_path),
            device=self._device,
        )
        self._tokenizer = open_clip.get_tokenizer(self.model_name)

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        return vector if norm == 0 else vector / norm

    def embed_text(self, text: str) -> np.ndarray:
        with self._torch.inference_mode():
            tokens = self._tokenizer([text])
            embedding = self._model.encode_text(tokens).cpu().numpy()[0].astype(np.float32)
        return self._normalize(embedding)

    def embed_image(
        self,
        image_path: Path,
        hint_text: str = "",
        image: Image.Image | None = None,
    ) -> np.ndarray:
        del hint_text
        source = image if image is not None else Image.open(image_path)
        try:
            image_input = self._preprocess(source.convert("RGB")).unsqueeze(0)
        finally:
            if image is None:
                source.close()
        with self._torch.inference_mode():
            embedding = self._model.encode_image(image_input).cpu().numpy()[0].astype(np.float32)
        return self._normalize(embedding)


class BgeSmallTextEmbedder(HashFallbackEmbedder):
    engine_name = "bge-small"
    model_name = "BAAI/bge-small-en-v1.5"
    degraded = False

    def __init__(self) -> None:
        import torch  # type: ignore
        from transformers import AutoModel, AutoTokenizer  # type: ignore

        self._torch = torch
        model_dir = resolve_bge_model_dir()
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self._model = AutoModel.from_pretrained(str(model_dir), local_files_only=True)
        self._model.eval()
        self.dimension = int(getattr(self._model.config, "hidden_size", 384))

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        return vector if norm == 0 else vector / norm

    def embed_text(self, text: str) -> np.ndarray:
        if not text.strip():
            return np.zeros(self.dimension, dtype=np.float32)
        encoded = self._tokenizer(
            [text],
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with self._torch.inference_mode():
            outputs = self._model(**encoded)
            token_embeddings = outputs.last_hidden_state
            attention_mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            pooled = (token_embeddings * attention_mask).sum(dim=1) / attention_mask.sum(dim=1).clamp(min=1e-9)
            vector = pooled[0].cpu().numpy().astype(np.float32)
        return self._normalize(vector)


def create_embedder() -> BaseImageEmbedder:
    return create_image_embedder()


def create_image_embedder() -> BaseImageEmbedder:
    try:
        return OpenClipImageEmbedder()
    except Exception:
        return BaseImageEmbedder()


def create_text_embedder() -> HashFallbackEmbedder:
    try:
        return BgeSmallTextEmbedder()
    except Exception:
        return HashFallbackEmbedder()


BaseEmbedder = BaseImageEmbedder


def resolve_model_root() -> Path:
    explicit = os.environ.get("RECALL_MODEL_ROOT", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.exists():
            return candidate

    candidates = [
        Path(__file__).resolve().parents[2] / "models",
        Path.cwd() / "python" / "models",
        Path.cwd() / "models",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "Recall local model assets were not found. Run `npm run prepare:models` before starting Recall."
    )


def resolve_openclip_checkpoint(checkpoint_name: str) -> Path:
    explicit = os.environ.get("RECALL_OPENCLIP_CHECKPOINT", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Configured RECALL_OPENCLIP_CHECKPOINT was not found: {candidate}")

    candidate = resolve_model_root() / OPENCLIP_MODEL_DIR / checkpoint_name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Recall OpenCLIP checkpoint is missing at {candidate}. Run `npm run prepare:models` first."
    )


def resolve_bge_model_dir() -> Path:
    explicit = os.environ.get("RECALL_BGE_MODEL_DIR", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Configured RECALL_BGE_MODEL_DIR was not found: {candidate}")

    candidate = resolve_model_root() / BGE_MODEL_DIR
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Recall text model assets are missing at {candidate}. Run `npm run prepare:models` first."
    )

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


@dataclass(slots=True)
class EmbeddingHealth:
    engine_name: str
    model_name: str
    degraded: bool
    dimension: int


class BaseEmbedder:
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
        color_tokens = f"r{round(color_summary[0])} g{round(color_summary[1])} b{round(color_summary[2])}"
        return self.embed_text(f"{image_path.name} {hint_text} {color_tokens}")


class OpenClipEmbedder(BaseEmbedder):
    engine_name = "openclip"
    model_name = "ViT-B-32"
    degraded = False
    dimension = 512
    repo_id = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    checkpoint_name = "open_clip_model.safetensors"

    def __init__(self) -> None:
        from huggingface_hub import hf_hub_download  # type: ignore
        import open_clip  # type: ignore
        import torch  # type: ignore

        self._torch = torch
        self._device = "cpu"
        checkpoint_path = hf_hub_download(
            repo_id=self.repo_id,
            filename=self.checkpoint_name,
            local_files_only=True,
        )
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            self.model_name,
            pretrained=checkpoint_path,
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


def create_embedder() -> BaseEmbedder:
    try:
        return OpenClipEmbedder()
    except Exception:
        return BaseEmbedder()

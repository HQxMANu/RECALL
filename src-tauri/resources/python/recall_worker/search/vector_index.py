from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


class NumpyVectorIndex:
    engine_name = "numpy-fallback"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self._vectors: dict[int, np.ndarray] = {}
        self.bootstrap_mode = "memory"

    def rebuild(self, embeddings: list[tuple[int, np.ndarray]]) -> None:
        self._vectors = {image_id: vector.astype(np.float32) for image_id, vector in embeddings}
        self.bootstrap_mode = "memory"

    def bootstrap(
        self,
        embeddings: list[tuple[int, np.ndarray]] | None = None,
        ids: list[int] | None = None,
    ) -> bool:
        del ids
        self.rebuild(embeddings or [])
        return True

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        self._vectors[image_id] = vector.astype(np.float32)

    def remove(self, image_id: int) -> None:
        self._vectors.pop(image_id, None)

    def search(self, query: np.ndarray, limit: int) -> list[tuple[int, float]]:
        if not self._vectors:
            return []
        scores = [
            (image_id, float(np.dot(query, vector)))
            for image_id, vector in self._vectors.items()
        ]
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:limit]


class FaissVectorIndex(NumpyVectorIndex):
    engine_name = "faiss"

    def __init__(self, dimension: int, index_path: Path) -> None:
        import faiss  # type: ignore

        super().__init__(dimension)
        self._faiss = faiss
        self._index_path = index_path
        self._meta_path = index_path.with_suffix(f"{index_path.suffix}.meta.json")
        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        self._ids: set[int] = set()

    def bootstrap(
        self,
        embeddings: list[tuple[int, np.ndarray]] | None = None,
        ids: list[int] | None = None,
    ) -> bool:
        if ids is not None and self._index_path.exists() and self._meta_path.exists():
            try:
                metadata = json.loads(self._meta_path.read_text(encoding="utf-8"))
                if (
                    metadata.get("dimension") == self.dimension
                    and metadata.get("count") == len(ids)
                    and metadata.get("signature") == _id_signature(sorted(ids))
                ):
                    self._index = self._faiss.read_index(str(self._index_path))
                    self._ids = set(ids)
                    self.bootstrap_mode = "persisted"
                    return True
            except Exception:
                pass

        if embeddings is None:
            return False

        self.rebuild(embeddings)
        return True

    def rebuild(self, embeddings: list[tuple[int, np.ndarray]]) -> None:
        self._index = self._faiss.IndexIDMap2(self._faiss.IndexFlatIP(self.dimension))
        self._ids.clear()
        if embeddings:
            ids = np.array([image_id for image_id, _ in embeddings], dtype=np.int64)
            vectors = np.stack([vector.astype(np.float32) for _, vector in embeddings], axis=0)
            self._index.add_with_ids(vectors, ids)
            self._ids = {image_id for image_id, _ in embeddings}
        self.bootstrap_mode = "rebuilt"
        self._save()

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        self.remove(image_id)
        array = vector.astype(np.float32)[None, :]
        ids = np.array([image_id], dtype=np.int64)
        self._index.add_with_ids(array, ids)
        self._ids.add(image_id)
        self._save()

    def remove(self, image_id: int) -> None:
        if image_id in self._ids:
            self._index.remove_ids(np.array([image_id], dtype=np.int64))
            self._ids.discard(image_id)
            self._save()

    def search(self, query: np.ndarray, limit: int) -> list[tuple[int, float]]:
        if not self._ids:
            return []
        scores, ids = self._index.search(query.astype(np.float32)[None, :], min(limit, len(self._ids)))
        return [
            (int(image_id), float(score))
            for image_id, score in zip(ids[0], scores[0], strict=False)
            if int(image_id) != -1
        ]

    def _save(self) -> None:
        self._faiss.write_index(self._index, str(self._index_path))
        metadata = {
            "dimension": self.dimension,
            "count": len(self._ids),
            "signature": _id_signature(sorted(self._ids)),
        }
        self._meta_path.write_text(json.dumps(metadata), encoding="utf-8")


def _id_signature(ids: list[int]) -> str:
    digest = hashlib.sha256()
    for image_id in ids:
        digest.update(f"{image_id}\n".encode("utf-8"))
    return digest.hexdigest()


def create_vector_index(dimension: int, index_path: Path) -> NumpyVectorIndex:
    try:
        return FaissVectorIndex(dimension, index_path)
    except Exception:
        return NumpyVectorIndex(dimension)

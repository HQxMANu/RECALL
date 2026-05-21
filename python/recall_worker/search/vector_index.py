from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np


class NumpyVectorIndex:
    engine_name = "numpy-fallback"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self._vectors: dict[int, np.ndarray] = {}
        self.bootstrap_mode = "memory"
        self._dirty = False
        self._count = 0
        self._rebuild_vectors: dict[int, np.ndarray] | None = None
        self._rebuild_in_place = False

    def rebuild(self, embeddings: list[tuple[int, np.ndarray]]) -> None:
        self.begin_rebuild()
        try:
            self.add_batch(embeddings)
            self.finish_rebuild()
        except Exception:
            self.abort_rebuild()
            raise

    def bootstrap(
        self,
        embeddings: list[tuple[int, np.ndarray]] | None = None,
        metadata: dict[str, int | str | None] | None = None,
    ) -> bool:
        del metadata
        if embeddings is None:
            return False
        self.rebuild(embeddings)
        return True

    def begin_rebuild(self) -> None:
        # The numpy fallback is already an in-memory degraded mode, so rebuild
        # directly into the live dictionary to avoid holding two full corpora.
        self._rebuild_vectors = self._vectors
        self._rebuild_vectors.clear()
        self._rebuild_in_place = True

    def add_batch(self, records: list[tuple[int, np.ndarray]]) -> None:
        if self._rebuild_vectors is None:
            raise RuntimeError("Vector rebuild has not been started")
        for image_id, vector in records:
            self._rebuild_vectors[image_id] = np.asarray(vector, dtype=np.float32)

    def finish_rebuild(self, metadata: dict[str, int | str | None] | None = None) -> None:
        del metadata
        if self._rebuild_vectors is None:
            raise RuntimeError("Vector rebuild has not been started")
        self._vectors = self._rebuild_vectors
        self._rebuild_vectors = None
        self._rebuild_in_place = False
        self._count = len(self._vectors)
        self._dirty = False
        self.bootstrap_mode = "rebuilt"

    def abort_rebuild(self) -> None:
        if self._rebuild_in_place:
            self._vectors = {}
        self._rebuild_vectors = None
        self._rebuild_in_place = False

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        self._vectors[image_id] = np.asarray(vector, dtype=np.float32)
        self._dirty = True
        self._count = len(self._vectors)

    def remove(self, image_id: int) -> None:
        if image_id in self._vectors:
            self._vectors.pop(image_id, None)
            self._dirty = True
            self._count = len(self._vectors)

    def flush(self, metadata: dict[str, int | str | None] | None = None) -> None:
        del metadata

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
        self._rebuild_index = None
        self._rebuild_count = 0

    def bootstrap(
        self,
        embeddings: list[tuple[int, np.ndarray]] | None = None,
        metadata: dict[str, int | str | None] | None = None,
    ) -> bool:
        if metadata is not None and self._index_path.exists() and self._meta_path.exists():
            try:
                stored_metadata = json.loads(self._meta_path.read_text(encoding="utf-8"))
                if (
                    int(stored_metadata.get("revision", -1)) == int(metadata.get("revision", -2))
                    and int(stored_metadata.get("count", -1)) == int(metadata.get("count", -2))
                    and stored_metadata.get("model_name") == metadata.get("model_name")
                    and int(stored_metadata.get("vector_dim", -1)) == int(metadata.get("vector_dim", -2))
                    and int(stored_metadata.get("dimension", -1)) == self.dimension
                ):
                    self._index = self._faiss.read_index(str(self._index_path))
                    self._ids = set()
                    self.bootstrap_mode = "persisted"
                    self._dirty = False
                    self._count = int(metadata.get("count") or 0)
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
        self._count = len(embeddings)
        self.bootstrap_mode = "rebuilt"
        self._dirty = True

    def begin_rebuild(self) -> None:
        self._rebuild_index = self._faiss.IndexIDMap2(self._faiss.IndexFlatIP(self.dimension))
        self._rebuild_count = 0

    def add_batch(self, records: list[tuple[int, np.ndarray]]) -> None:
        if self._rebuild_index is None:
            raise RuntimeError("Vector rebuild has not been started")
        if not records:
            return
        ids = np.array([image_id for image_id, _ in records], dtype=np.int64)
        vectors = np.stack([vector.astype(np.float32) for _, vector in records], axis=0)
        self._rebuild_index.add_with_ids(vectors, ids)
        self._rebuild_count += len(records)

    def finish_rebuild(self, metadata: dict[str, int | str | None] | None = None) -> None:
        if self._rebuild_index is None:
            raise RuntimeError("Vector rebuild has not been started")
        self._write_snapshot(self._rebuild_index, self._rebuild_count, metadata)
        self._index = self._rebuild_index
        self._rebuild_index = None
        rebuild_count = self._rebuild_count
        self._rebuild_count = 0
        self._ids = set()
        self._count = int((metadata or {}).get("count") or rebuild_count)
        self.bootstrap_mode = "rebuilt"
        self._dirty = False

    def abort_rebuild(self) -> None:
        self._rebuild_index = None
        self._rebuild_count = 0

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        self.remove(image_id)
        array = vector.astype(np.float32)[None, :]
        ids = np.array([image_id], dtype=np.int64)
        self._index.add_with_ids(array, ids)
        self._ids.add(image_id)
        self._dirty = True
        self._count += 1

    def remove(self, image_id: int) -> None:
        if image_id in self._ids or self._count > 0:
            removed = int(self._index.remove_ids(np.array([image_id], dtype=np.int64)))
            self._ids.discard(image_id)
            if removed > 0:
                self._dirty = True
                self._count = max(0, self._count - removed)

    def flush(self, metadata: dict[str, int | str | None] | None = None) -> None:
        if not self._dirty:
            return
        self._write_snapshot(self._index, self._count, metadata)
        self._dirty = False

    def search(self, query: np.ndarray, limit: int) -> list[tuple[int, float]]:
        if self._count <= 0:
            return []
        scores, ids = self._index.search(query.astype(np.float32)[None, :], min(limit, self._count))
        return [
            (int(image_id), float(score))
            for image_id, score in zip(ids[0], scores[0], strict=False)
            if int(image_id) != -1
        ]

    def _write_snapshot(
        self,
        index,
        count: int,
        metadata: dict[str, int | str | None] | None = None,
    ) -> None:
        temp_index_path = self._index_path.with_suffix(f"{self._index_path.suffix}.tmp")
        temp_meta_path = self._meta_path.with_suffix(f"{self._meta_path.suffix}.tmp")
        self._faiss.write_index(index, str(temp_index_path))
        metadata = {
            "dimension": self.dimension,
            "count": count,
            "revision": int((metadata or {}).get("revision") or 0),
            "model_name": (metadata or {}).get("model_name"),
            "vector_dim": int((metadata or {}).get("vector_dim") or self.dimension),
        }
        temp_meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        os.replace(temp_index_path, self._index_path)
        os.replace(temp_meta_path, self._meta_path)


def create_vector_index(dimension: int, index_path: Path) -> NumpyVectorIndex:
    try:
        return FaissVectorIndex(dimension, index_path)
    except Exception:
        return NumpyVectorIndex(dimension)

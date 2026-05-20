import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from recall_worker.api.server import RecallWorker


class FakeDatabase:
    def __init__(self) -> None:
        self.iter_calls = 0
        self.list_all_embeddings_calls = 0

    def recover_running_jobs(self, finished_at: str, error_message: str) -> None:
        del finished_at, error_message

    def get_embeddings_state(self) -> dict[str, int | str | None]:
        return {
            "revision": 3,
            "count": 2,
            "model_name": "dummy-model",
            "vector_dim": 4,
        }

    def iter_embedding_batches(self, batch_size: int):
        self.iter_calls += 1
        del batch_size
        yield [
            (1, np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)),
            (2, np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)),
        ]

    def list_all_embeddings(self):
        self.list_all_embeddings_calls += 1
        return []


class FakeVectorIndex:
    engine_name = "faiss"

    def __init__(self) -> None:
        self.bootstrap_mode = "unknown"
        self.batches: list[list[tuple[int, np.ndarray]]] = []
        self.finished_metadata = None

    def bootstrap(self, embeddings=None, metadata=None) -> bool:
        del embeddings, metadata
        return False

    def begin_rebuild(self) -> None:
        self.batches.clear()

    def add_batch(self, records: list[tuple[int, np.ndarray]]) -> None:
        self.batches.append(records)

    def finish_rebuild(self, metadata) -> None:
        self.finished_metadata = metadata
        self.bootstrap_mode = "rebuilt"

    def abort_rebuild(self) -> None:
        self.batches.clear()


class FakeThread:
    def __init__(self, target=None, daemon=None, name=None) -> None:
        del daemon, name
        self.target = target

    def start(self) -> None:
        return None


class WorkerStartupTests(unittest.TestCase):
    def test_worker_streams_embedding_rebuild_batches(self) -> None:
        fake_database = FakeDatabase()
        fake_vector_index = FakeVectorIndex()
        config = SimpleNamespace(
            database_path=Path(tempfile.gettempdir()) / "recall-test.db",
            vector_index_path=Path(tempfile.gettempdir()) / "recall-test.faiss",
            search_limit=200,
        )
        fake_embedder = SimpleNamespace(
            dimension=4,
            engine_name="openclip",
            degraded=False,
        )

        with (
            patch("recall_worker.api.server.load_config", return_value=config),
            patch("recall_worker.api.server.Database", return_value=fake_database),
            patch(
                "recall_worker.api.server.create_ocr_engine",
                return_value=SimpleNamespace(
                    engine_name="deferred",
                    status=lambda: {
                        "phase": "deferred",
                        "engine_name": "deferred",
                        "degraded": False,
                        "last_error": None,
                        "last_init_ms": None,
                    },
                ),
            ),
            patch("recall_worker.api.server.create_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_vector_index", return_value=fake_vector_index),
            patch("recall_worker.api.server.IndexingPipeline", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.SearchService", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.threading.Thread", FakeThread),
        ):
            RecallWorker()

        self.assertEqual(fake_database.iter_calls, 1)
        self.assertEqual(fake_database.list_all_embeddings_calls, 0)
        self.assertEqual(len(fake_vector_index.batches), 1)
        self.assertEqual(fake_vector_index.finished_metadata["count"], 2)


if __name__ == "__main__":
    unittest.main()

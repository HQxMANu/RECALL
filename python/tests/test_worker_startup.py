import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from recall_worker.api.server import RecallWorker


class FakeDatabase:
    def __init__(
        self,
        *,
        needs_mixed_asset_rescan: bool = True,
        active_folder_ids: list[int] | None = None,
    ) -> None:
        self.iter_calls = 0
        self.list_all_embeddings_calls = 0
        self.mixed_asset_rescan_complete = False
        self._needs_mixed_asset_rescan = needs_mixed_asset_rescan
        self._active_folder_ids = active_folder_ids if active_folder_ids is not None else [11, 12]

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

    def needs_mixed_asset_rescan(self) -> bool:
        return self._needs_mixed_asset_rescan

    def get_active_folder_records(self):
        return [{"id": folder_id} for folder_id in self._active_folder_ids]

    def mark_mixed_asset_rescan_complete(self) -> None:
        self.mixed_asset_rescan_complete = True


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
            model_name="dummy-model",
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
            patch(
                "recall_worker.api.server.create_transcription_engine",
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
            patch("recall_worker.api.server.create_image_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_text_embedder", return_value=fake_embedder),
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
        self.assertFalse(fake_database.mixed_asset_rescan_complete)

    def test_worker_enqueues_mixed_asset_rescan_for_existing_folders(self) -> None:
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
            model_name="dummy-model",
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
            patch(
                "recall_worker.api.server.create_transcription_engine",
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
            patch("recall_worker.api.server.create_image_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_text_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_vector_index", return_value=fake_vector_index),
            patch("recall_worker.api.server.IndexingPipeline", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.SearchService", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.threading.Thread", FakeThread),
        ):
            worker = RecallWorker()

        self.assertEqual(len(worker._full_index_jobs), 1)
        self.assertEqual(worker._full_index_jobs[0]["folderIds"], [11, 12])
        self.assertTrue(worker._full_index_jobs[0]["markMixedAssetRescanOnSuccess"])
        self.assertEqual(worker._full_index_jobs[0]["triggerSource"], "mixed_asset_upgrade")

    def test_worker_enqueues_startup_reconcile_for_existing_folders(self) -> None:
        fake_database = FakeDatabase(needs_mixed_asset_rescan=False, active_folder_ids=[21, 22])
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
            model_name="dummy-model",
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
            patch(
                "recall_worker.api.server.create_transcription_engine",
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
            patch("recall_worker.api.server.create_image_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_text_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_vector_index", return_value=fake_vector_index),
            patch("recall_worker.api.server.IndexingPipeline", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.SearchService", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.threading.Thread", FakeThread),
        ):
            worker = RecallWorker()

        self.assertEqual(len(worker._full_index_jobs), 1)
        self.assertEqual(worker._full_index_jobs[0]["folderIds"], [21, 22])
        self.assertEqual(worker._full_index_jobs[0]["triggerSource"], "startup_reconcile")
        self.assertNotIn("markMixedAssetRescanOnSuccess", worker._full_index_jobs[0])
        self.assertFalse(fake_database.mixed_asset_rescan_complete)

    def test_worker_marks_mixed_asset_rescan_complete_when_no_folders_exist(self) -> None:
        fake_database = FakeDatabase(needs_mixed_asset_rescan=True, active_folder_ids=[])
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
            model_name="dummy-model",
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
            patch(
                "recall_worker.api.server.create_transcription_engine",
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
            patch("recall_worker.api.server.create_image_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_text_embedder", return_value=fake_embedder),
            patch("recall_worker.api.server.create_vector_index", return_value=fake_vector_index),
            patch("recall_worker.api.server.IndexingPipeline", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.SearchService", return_value=SimpleNamespace()),
            patch("recall_worker.api.server.threading.Thread", FakeThread),
        ):
            worker = RecallWorker()

        self.assertEqual(worker._full_index_jobs, [])
        self.assertTrue(fake_database.mixed_asset_rescan_complete)


if __name__ == "__main__":
    unittest.main()

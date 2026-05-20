import tempfile
import unittest
from pathlib import Path

import numpy as np

from recall_worker.db.database import Database


class DatabaseTests(unittest.TestCase):
    def test_folder_insert_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "recall.db")
            added, skipped = database.add_or_reactivate_folders(
                ["C:\\Images\\Screenshots"],
                "2026-05-14T00:00:00+00:00",
            )

            self.assertEqual(skipped, [])
            self.assertEqual(len(added), 1)
            self.assertEqual(database.list_folders()[0]["displayName"], "Screenshots")
            database.close()

    def test_embedding_batch_updates_revision_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "recall.db")
            added, _ = database.add_or_reactivate_folders(
                ["C:\\Images"],
                "2026-05-14T00:00:00+00:00",
            )
            image_ids = database.upsert_images_batch(
                [
                    {
                        "folder_id": added[0]["id"],
                        "path": "C:\\Images\\one.png",
                        "filename": "one.png",
                        "extension": ".png",
                        "content_hash": "hash-one",
                        "created_at_fs": "2026-05-14T00:00:00+00:00",
                        "modified_at_fs": "2026-05-14T00:00:00+00:00",
                        "file_size_bytes": 100,
                        "width": 10,
                        "height": 10,
                        "ocr_text": "hello",
                        "thumbnail_path": None,
                        "last_indexed_at": "2026-05-14T00:00:00+00:00",
                        "index_status": "ready",
                        "error_code": None,
                        "error_message": None,
                    }
                ]
            )

            revision = database.upsert_embeddings_batch(
                [
                    (
                        image_ids["C:\\Images\\one.png"],
                        "dummy-model",
                        np.array([1.0, 0.0, 0.0], dtype=np.float32),
                        "2026-05-14T00:00:00+00:00",
                    )
                ]
            )
            state = database.get_embeddings_state()

            self.assertEqual(revision, 1)
            self.assertEqual(state["revision"], 1)
            self.assertEqual(state["count"], 1)
            self.assertEqual(state["model_name"], "dummy-model")
            self.assertEqual(state["vector_dim"], 3)
            database.close()

    def test_iter_embedding_batches_returns_ordered_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "recall.db")
            added, _ = database.add_or_reactivate_folders(
                ["C:\\Images"],
                "2026-05-14T00:00:00+00:00",
            )
            image_ids = database.upsert_images_batch(
                [
                    {
                        "folder_id": added[0]["id"],
                        "path": f"C:\\Images\\{name}.png",
                        "filename": f"{name}.png",
                        "extension": ".png",
                        "content_hash": f"hash-{name}",
                        "created_at_fs": "2026-05-14T00:00:00+00:00",
                        "modified_at_fs": "2026-05-14T00:00:00+00:00",
                        "file_size_bytes": 100,
                        "width": 10,
                        "height": 10,
                        "ocr_text": name,
                        "thumbnail_path": None,
                        "last_indexed_at": "2026-05-14T00:00:00+00:00",
                        "index_status": "ready",
                        "error_code": None,
                        "error_message": None,
                    }
                    for name in ["b", "a", "c"]
                ]
            )
            database.upsert_embeddings_batch(
                [
                    (
                        image_ids[path],
                        "dummy-model",
                        np.array([index, 0.0, 0.0], dtype=np.float32),
                        "2026-05-14T00:00:00+00:00",
                    )
                    for index, path in enumerate(sorted(image_ids.keys()), start=1)
                ]
            )

            batches = list(database.iter_embedding_batches(2))

            self.assertEqual([image_id for batch in batches for image_id, _ in batch], sorted(image_ids.values()))
            self.assertEqual([len(batch) for batch in batches], [2, 1])
            database.close()


if __name__ == "__main__":
    unittest.main()

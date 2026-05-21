import tempfile
import unittest
import sqlite3
from pathlib import Path

import numpy as np

from recall_worker.db.database import (
    Database,
    IMAGE_ASSET_BACKFILL_KEY,
    IMAGE_ASSET_BACKFILL_VERSION,
    SCHEMA_SQL,
)


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

    def test_image_asset_backfill_runs_once_for_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "recall.db"
            legacy = sqlite3.connect(database_path)
            legacy.row_factory = sqlite3.Row
            legacy.executescript(SCHEMA_SQL)
            legacy.execute(
                """
                INSERT INTO indexed_folders(path, display_name, is_active, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (
                    "C:\\Images",
                    "Images",
                    "2026-05-14T00:00:00+00:00",
                    "2026-05-14T00:00:00+00:00",
                ),
            )
            legacy.execute(
                """
                INSERT INTO indexed_images(
                  folder_id, path, filename, extension, content_hash, created_at_fs, modified_at_fs,
                  file_size_bytes, width, height, ocr_text, thumbnail_path,
                  last_indexed_at, index_status, error_code, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "C:\\Images\\legacy.png",
                    "legacy.png",
                    ".png",
                    "legacy-hash",
                    "2026-05-14T00:00:00+00:00",
                    "2026-05-14T00:00:00+00:00",
                    128,
                    32,
                    32,
                    "legacy ocr",
                    "C:\\thumbs\\legacy.jpg",
                    "2026-05-14T00:00:00+00:00",
                    "ready",
                    None,
                    None,
                ),
            )
            legacy.commit()
            legacy.close()

            database = Database(database_path)
            database.close()

            verify = sqlite3.connect(database_path)
            verify.row_factory = sqlite3.Row
            first_asset = verify.execute(
                "SELECT id, preview_path FROM indexed_assets WHERE path = ?",
                ("C:\\Images\\legacy.png",),
            ).fetchone()
            first_chunk = verify.execute(
                """
                SELECT id, chunk_text
                FROM asset_chunks
                WHERE asset_id = ?
                """,
                (first_asset["id"],),
            ).fetchone()
            marker = verify.execute(
                "SELECT value_json FROM app_settings WHERE key = ?",
                (IMAGE_ASSET_BACKFILL_KEY,),
            ).fetchone()
            verify.close()

            self.assertIsNotNone(first_asset)
            self.assertEqual(first_asset["preview_path"], "C:\\thumbs\\legacy.jpg")
            self.assertIsNotNone(first_chunk)
            self.assertEqual(first_chunk["chunk_text"], "legacy ocr")
            self.assertEqual(int(marker["value_json"]), IMAGE_ASSET_BACKFILL_VERSION)

            database = Database(database_path)
            database.close()

            verify = sqlite3.connect(database_path)
            verify.row_factory = sqlite3.Row
            second_asset = verify.execute(
                "SELECT id FROM indexed_assets WHERE path = ?",
                ("C:\\Images\\legacy.png",),
            ).fetchone()
            second_chunk = verify.execute(
                """
                SELECT id
                FROM asset_chunks
                WHERE asset_id = ?
                """,
                (second_asset["id"],),
            ).fetchone()
            verify.close()

            self.assertEqual(second_asset["id"], first_asset["id"])
            self.assertEqual(second_chunk["id"], first_chunk["id"])


if __name__ == "__main__":
    unittest.main()

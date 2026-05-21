import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from recall_worker.core.config import AppConfig
from recall_worker.db.database import Database
from recall_worker.indexing.pipeline import IndexingPipeline


class FlakyOcrEngine:
    def __init__(self) -> None:
        self.ready_calls = 0

    def extract_text(self, image_path: Path) -> str:
        if image_path.name.startswith("bad"):
            raise RuntimeError("ocr exploded")
        return "hello world"

    def ensure_ready(self) -> "FlakyOcrEngine":
        self.ready_calls += 1
        return self


class DummyEmbedder:
    model_name = "dummy"

    def embed_image(self, image_path: Path, hint_text: str = "", image: Image.Image | None = None) -> np.ndarray:
        del image_path, hint_text, image
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        del text
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class RecordingVectorIndex:
    def __init__(self) -> None:
        self.upserts: list[int] = []
        self.removals: list[int] = []
        self.flush_calls = 0

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        del vector
        self.upserts.append(image_id)

    def remove(self, image_id: int) -> None:
        self.removals.append(image_id)

    def flush(self, metadata: dict | None = None) -> None:
        del metadata
        self.flush_calls += 1


class IndexingPipelineTests(unittest.TestCase):
    def test_scan_folder_continues_when_ocr_fails_for_one_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder_path = root / "Photos"
            folder_path.mkdir()
            self._create_image(folder_path / "bad-passport.jpg", (220, 140))
            self._create_image(folder_path / "good-note.png", (220, 140))

            config = AppConfig(
                app_data_dir=root,
                database_path=root / "recall.db",
                thumbnail_dir=root / "thumbnails",
                vector_index_path=root / "recall.faiss",
                max_thumbnail_size=320,
                search_limit=200,
            )
            config.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            database = Database(config.database_path)
            added, _ = database.add_or_reactivate_folders(
                [str(folder_path)],
                "2026-05-16T00:00:00+00:00",
            )
            folder_id = int(added[0]["id"])
            vector_index = RecordingVectorIndex()
            ocr_engine = FlakyOcrEngine()
            pipeline = IndexingPipeline(
                config,
                database,
                ocr_engine,
                DummyEmbedder(),
                vector_index,
            )

            progress_updates: list[tuple[int, int]] = []
            pipeline.scan_folder(
                {"id": folder_id, "path": str(folder_path)},
                lambda total, processed: progress_updates.append((total, processed)),
            )

            bad_row = database.get_image_by_path(str(folder_path / "bad-passport.jpg"))
            good_row = database.get_image_by_path(str(folder_path / "good-note.png"))

            self.assertIsNotNone(bad_row)
            self.assertIsNotNone(good_row)
            self.assertEqual(bad_row["index_status"], "ready")
            self.assertEqual(bad_row["ocr_text"], "")
            self.assertEqual(bad_row["error_code"], "RuntimeError")
            self.assertEqual(good_row["index_status"], "ready")
            self.assertEqual(good_row["ocr_text"], "hello world")
            self.assertEqual(len(vector_index.upserts), 3)
            self.assertGreaterEqual(vector_index.flush_calls, 1)
            self.assertEqual(progress_updates[-1], (2, 2))
            self.assertEqual(ocr_engine.ready_calls, 1)
            database.close()

    def test_process_events_flushes_large_batches_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder_path = root / "Photos"
            folder_path.mkdir()
            for index in range(65):
                self._create_image(folder_path / f"image-{index}.png", (220, 140))

            config = AppConfig(
                app_data_dir=root,
                database_path=root / "recall.db",
                thumbnail_dir=root / "thumbnails",
                vector_index_path=root / "recall.faiss",
                max_thumbnail_size=320,
                search_limit=200,
            )
            config.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            database = Database(config.database_path)
            added, _ = database.add_or_reactivate_folders(
                [str(folder_path)],
                "2026-05-16T00:00:00+00:00",
            )
            vector_index = RecordingVectorIndex()
            ocr_engine = FlakyOcrEngine()
            pipeline = IndexingPipeline(
                config,
                database,
                ocr_engine,
                DummyEmbedder(),
                vector_index,
            )

            pipeline.process_events(
                [
                    {"kind": "modify", "path": str(folder_path / f"image-{index}.png")}
                    for index in range(65)
                ],
                [{"id": added[0]["id"], "path": str(folder_path)}],
            )

            self.assertEqual(len(vector_index.upserts), 130)
            self.assertGreaterEqual(vector_index.flush_calls, 2)
            self.assertEqual(ocr_engine.ready_calls, 1)
            database.close()

    def test_scan_folder_retries_non_ready_document_without_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder_path = root / "Docs"
            folder_path.mkdir()
            document_path = folder_path / "notes.txt"
            document_path.write_text("literature review about software engineering and AI", encoding="utf-8")

            config = AppConfig(
                app_data_dir=root,
                database_path=root / "recall.db",
                thumbnail_dir=root / "thumbnails",
                vector_index_path=root / "recall.faiss",
                max_thumbnail_size=320,
                search_limit=200,
            )
            config.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            database = Database(config.database_path)
            added, _ = database.add_or_reactivate_folders(
                [str(folder_path)],
                "2026-05-16T00:00:00+00:00",
            )
            folder_id = int(added[0]["id"])
            vector_index = RecordingVectorIndex()
            pipeline = IndexingPipeline(
                config,
                database,
                FlakyOcrEngine(),
                DummyEmbedder(),
                vector_index,
            )

            stat = document_path.stat()
            created_iso = datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
            modified_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            database.upsert_assets_batch(
                [
                    {
                        "folder_id": folder_id,
                        "asset_type": "document",
                        "path": str(document_path),
                        "filename": document_path.name,
                        "extension": document_path.suffix.lower(),
                        "content_hash": "broken",
                        "created_at_fs": created_iso,
                        "modified_at_fs": modified_iso,
                        "file_size_bytes": stat.st_size,
                        "width": None,
                        "height": None,
                        "duration_ms": None,
                        "preview_path": None,
                        "last_indexed_at": created_iso,
                        "index_status": "error",
                        "error_code": "ModuleNotFoundError",
                        "error_message": "No module named 'docx'",
                    }
                ]
            )
            database._connection.execute(  # noqa: SLF001
                "UPDATE indexed_assets SET modified_at_fs = ? WHERE path = ?",
                (
                    modified_iso,
                    str(document_path),
                ),
            )
            database._connection.commit()  # noqa: SLF001

            pipeline.scan_folder(
                {"id": folder_id, "path": str(folder_path)},
                lambda total, processed: None,
            )

            asset = database.get_asset_by_path(str(document_path))
            self.assertIsNotNone(asset)
            self.assertEqual(asset["index_status"], "ready")
            chunk_count = database._connection.execute(  # noqa: SLF001
                """
                SELECT COUNT(*)
                FROM asset_chunks c
                JOIN indexed_assets a ON a.id = c.asset_id
                WHERE a.path = ?
                """,
                (str(document_path),),
            ).fetchone()[0]
            self.assertGreater(chunk_count, 0)
            database.close()

    def test_scan_folder_generates_document_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder_path = root / "Docs"
            folder_path.mkdir()
            document_path = folder_path / "overview.txt"
            document_path.write_text(
                "This is the first page preview text for the literature review document. "
                "It should render into a document thumbnail.",
                encoding="utf-8",
            )

            config = AppConfig(
                app_data_dir=root,
                database_path=root / "recall.db",
                thumbnail_dir=root / "thumbnails",
                vector_index_path=root / "recall.faiss",
                max_thumbnail_size=320,
                search_limit=200,
            )
            config.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            database = Database(config.database_path)
            added, _ = database.add_or_reactivate_folders(
                [str(folder_path)],
                "2026-05-16T00:00:00+00:00",
            )
            pipeline = IndexingPipeline(
                config,
                database,
                FlakyOcrEngine(),
                DummyEmbedder(),
                RecordingVectorIndex(),
            )

            pipeline.scan_folder(
                {"id": added[0]["id"], "path": str(folder_path)},
                lambda total, processed: None,
            )

            asset = database.get_asset_by_path(str(document_path))
            self.assertIsNotNone(asset)
            self.assertEqual(asset["index_status"], "ready")
            self.assertTrue(asset["preview_path"])
            self.assertTrue(Path(asset["preview_path"]).exists())
            database.close()

    @staticmethod
    def _create_image(path: Path, size: tuple[int, int]) -> None:
        image = Image.new("RGB", size, color=(32, 32, 32))
        image.save(path)


if __name__ == "__main__":
    unittest.main()

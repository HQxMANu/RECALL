import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from recall_worker.core.config import AppConfig
from recall_worker.db.database import Database
from recall_worker.indexing.pipeline import IndexingPipeline


class FlakyOcrEngine:
    def extract_text(self, image_path: Path) -> str:
        if image_path.name.startswith("bad"):
            raise RuntimeError("ocr exploded")
        return "hello world"

    def ensure_ready(self) -> "FlakyOcrEngine":
        return self


class DummyEmbedder:
    model_name = "dummy"

    def embed_image(self, image_path: Path, hint_text: str = "") -> np.ndarray:
        del image_path, hint_text
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


class RecordingVectorIndex:
    def __init__(self) -> None:
        self.upserts: list[int] = []
        self.removals: list[int] = []

    def upsert(self, image_id: int, vector: np.ndarray) -> None:
        del vector
        self.upserts.append(image_id)

    def remove(self, image_id: int) -> None:
        self.removals.append(image_id)


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
            pipeline = IndexingPipeline(
                config,
                database,
                FlakyOcrEngine(),
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
            self.assertEqual(len(vector_index.upserts), 2)
            self.assertEqual(progress_updates[-1], (2, 2))
            database.close()

    @staticmethod
    def _create_image(path: Path, size: tuple[int, int]) -> None:
        image = Image.new("RGB", size, color=(32, 32, 32))
        image.save(path)


if __name__ == "__main__":
    unittest.main()

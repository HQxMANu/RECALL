import tempfile
import unittest
from pathlib import Path

from PIL import Image

from recall_worker.embeddings.engine import BaseEmbedder


class HashEmbedderTests(unittest.TestCase):
    def test_embed_text_returns_stable_dimension(self) -> None:
        embedder = BaseEmbedder()
        vector = embedder.embed_text("wifi password screenshot")
        self.assertEqual(vector.shape[0], embedder.dimension)

    def test_embed_image_runs_without_optional_ml_packages(self) -> None:
        embedder = BaseEmbedder()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            Image.new("RGB", (16, 16), color=(32, 90, 180)).save(image_path)
            vector = embedder.embed_image(image_path, "sample hint")
        self.assertEqual(vector.shape[0], embedder.dimension)


if __name__ == "__main__":
    unittest.main()

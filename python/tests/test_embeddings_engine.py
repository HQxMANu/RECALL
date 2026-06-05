import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recall_worker.embeddings import engine


class EmbeddingEnginePathTests(unittest.TestCase):
    def test_resolve_model_root_prefers_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_root = Path(temp_dir)
            with patch.dict(os.environ, {"RECALL_MODEL_ROOT": str(model_root)}, clear=False):
                self.assertEqual(engine.resolve_model_root(), model_root.resolve())

    def test_resolve_openclip_checkpoint_uses_local_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_root = Path(temp_dir)
            checkpoint = model_root / engine.OPENCLIP_MODEL_DIR / "open_clip_model.safetensors"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_bytes(b"checkpoint")

            with patch.dict(os.environ, {"RECALL_MODEL_ROOT": str(model_root)}, clear=False):
                self.assertEqual(
                    engine.resolve_openclip_checkpoint("open_clip_model.safetensors").resolve(),
                    checkpoint.resolve(),
                )

    def test_resolve_bge_model_dir_uses_local_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_root = Path(temp_dir)
            model_dir = model_root / engine.BGE_MODEL_DIR
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "config.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"RECALL_MODEL_ROOT": str(model_root)}, clear=False):
                self.assertEqual(engine.resolve_bge_model_dir().resolve(), model_dir.resolve())

    def test_missing_local_models_raise_actionable_error(self) -> None:
        missing_root = Path(tempfile.gettempdir()) / "missing-recall-model-root"
        with patch("recall_worker.embeddings.engine.resolve_model_root", return_value=missing_root):
            with self.assertRaises(FileNotFoundError) as error:
                engine.resolve_openclip_checkpoint("open_clip_model.safetensors")

        self.assertIn("npm run prepare:models", str(error.exception))


if __name__ == "__main__":
    unittest.main()

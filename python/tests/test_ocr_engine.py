from pathlib import Path
import unittest
from unittest import mock

from recall_worker.ocr.engine import (
    LazyOcrEngine,
    PaddleOcrEngine,
    TesseractOcrEngine,
    _extract_paddle_text_lines,
    _preferred_engine_types,
)


class FakePaddlePredictor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def predict(self, image_path: str, **kwargs):
        self.calls.append((image_path, kwargs))
        return self.result


class PaddleOcrEngineTests(unittest.TestCase):
    def test_extract_text_uses_predict_api(self) -> None:
        predictor = FakePaddlePredictor([{"rec_texts": ["hello", "world"]}])
        engine = object.__new__(PaddleOcrEngine)
        engine._ocr = predictor

        text = engine.extract_text(Path("sample.png"))

        self.assertEqual(text, "hello\nworld")
        self.assertEqual(
            predictor.calls,
            [("sample.png", {"use_textline_orientation": True})],
        )

    def test_extract_paddle_text_lines_supports_v3_result_shape(self) -> None:
        lines = _extract_paddle_text_lines(
            [
                {"rec_texts": ["passport", "details"]},
                {"rec_texts": ["wifi password"]},
            ]
        )

        self.assertEqual(lines, ["passport", "details", "wifi password"])

    def test_extract_paddle_text_lines_supports_legacy_result_shape(self) -> None:
        lines = _extract_paddle_text_lines(
            [
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("alpha", 0.99)],
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("beta", 0.95)],
                ]
            ]
        )

        self.assertEqual(lines, ["alpha", "beta"])

    def test_lazy_engine_falls_back_to_tesseract_when_paddle_runtime_fails(self) -> None:
        predictor = FakePaddlePredictor(None)

        def crash(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("predictor failed")

        predictor.predict = crash
        paddle_engine = object.__new__(PaddleOcrEngine)
        paddle_engine._ocr = predictor

        fallback_engine = mock.Mock()
        fallback_engine.engine_name = "tesseract"
        fallback_engine.degraded = False
        fallback_engine.extract_text.return_value = "fallback text"

        engine = LazyOcrEngine()
        engine._engine = paddle_engine
        engine.engine_name = paddle_engine.engine_name
        engine.degraded = paddle_engine.degraded
        engine._phase = "ready"

        with mock.patch("recall_worker.ocr.engine.TesseractOcrEngine", return_value=fallback_engine):
            text = engine.extract_text(Path("sample.png"))

        self.assertEqual(text, "fallback text")
        self.assertEqual(engine.engine_name, "tesseract")
        self.assertTrue(engine.degraded)
        self.assertEqual(engine.status()["phase"], "ready")
        self.assertIn("PaddleOCR runtime inference failed", engine.status()["last_error"])

    def test_windows_prefers_tesseract_by_default(self) -> None:
        with (
            mock.patch("recall_worker.ocr.engine.sys.platform", "win32"),
            mock.patch.dict("os.environ", {}, clear=False),
        ):
            engines = _preferred_engine_types()

        self.assertEqual(engines[0], TesseractOcrEngine)
        self.assertEqual(engines[1], PaddleOcrEngine)


if __name__ == "__main__":
    unittest.main()

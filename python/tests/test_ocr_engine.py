from pathlib import Path
import unittest

from recall_worker.ocr.engine import PaddleOcrEngine, _extract_paddle_text_lines


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


if __name__ == "__main__":
    unittest.main()

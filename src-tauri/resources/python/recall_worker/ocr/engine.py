from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any

from PIL import Image, ImageDraw


@dataclass(slots=True)
class OcrResult:
    engine_name: str
    degraded: bool
    text: str


class OcrEngine:
    engine_name = "none"
    degraded = True

    def extract_text(self, image_path: Path) -> str:
        return ""


class PaddleOcrEngine(OcrEngine):
    engine_name = "paddleocr"
    degraded = False

    def __init__(self) -> None:
        from paddleocr import PaddleOCR  # type: ignore

        self._ocr = PaddleOCR(lang="en", use_textline_orientation=True)

    def extract_text(self, image_path: Path) -> str:
        result = self._ocr.predict(
            str(image_path),
            use_textline_orientation=True,
        )
        lines = _extract_paddle_text_lines(result)
        return "\n".join(lines).strip()


class TesseractOcrEngine(OcrEngine):
    engine_name = "tesseract"
    degraded = False

    def __init__(self) -> None:
        import pytesseract  # type: ignore

        tesseract_candidates = [
            os.environ.get("TESSERACT_CMD"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in tesseract_candidates:
            if candidate and Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                break
        self._pytesseract = pytesseract

    def extract_text(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            return self._pytesseract.image_to_string(image).strip()


class LazyOcrEngine(OcrEngine):
    engine_name = "deferred"
    degraded = False

    def __init__(self) -> None:
        self._engine: OcrEngine | None = None
        self._phase = "deferred"
        self._last_error: str | None = None
        self._last_init_ms: int | None = None
        self._lock = threading.RLock()

    def extract_text(self, image_path: Path) -> str:
        return self.ensure_ready().extract_text(image_path)

    def ensure_ready(self) -> OcrEngine:
        if self._engine is not None:
            return self._engine

        with self._lock:
            if self._engine is not None:
                return self._engine

            self._phase = "warming"
            started = time.perf_counter()
            loaded_engine = _load_ocr_engine()
            self._last_init_ms = round((time.perf_counter() - started) * 1000)

            self._engine = loaded_engine
            self.engine_name = loaded_engine.engine_name
            self.degraded = loaded_engine.degraded
            self._phase = "ready" if self.engine_name != "none" else "limited"
            self._last_error = None if self.engine_name != "none" else "No OCR engine was available."
            print(
                f"OCR engine initialized with {self.engine_name} in {self._last_init_ms} ms",
                file=sys.stderr,
                flush=True,
            )
            return self._engine

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self._phase,
                "engine_name": self.engine_name,
                "degraded": self.degraded,
                "last_error": self._last_error,
                "last_init_ms": self._last_init_ms,
            }


def create_ocr_engine() -> LazyOcrEngine:
    return LazyOcrEngine()


def _load_ocr_engine() -> OcrEngine:
    for engine_type in (PaddleOcrEngine, TesseractOcrEngine):
        try:
            engine = engine_type()
            if engine_type is PaddleOcrEngine and os.environ.get("RECALL_VALIDATE_OCR_ON_BOOT") == "1":
                _validate_paddle_engine(engine)
            return engine
        except Exception:
            continue
    return OcrEngine()


def _validate_paddle_engine(engine: PaddleOcrEngine) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "ocr-smoke.png"
        image = Image.new("RGB", (600, 160), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.text((20, 60), "recall paddle smoke", fill=(0, 0, 0))
        image.save(image_path)
        engine.extract_text(image_path)


def _extract_paddle_text_lines(result: Any) -> list[str]:
    lines: list[str] = []
    for page in _as_sequence(result):
        lines.extend(_extract_paddle_page_lines(page))
    return [line for line in (item.strip() for item in lines) if line]


def _extract_paddle_page_lines(page: Any) -> list[str]:
    if page is None:
        return []

    mapping = _as_mapping(page)
    if mapping is not None:
        rec_texts = mapping.get("rec_texts")
        if isinstance(rec_texts, (list, tuple)):
            return [str(item) for item in rec_texts if str(item).strip()]

        text_word = mapping.get("text_word")
        if isinstance(text_word, (list, tuple)):
            return [str(item) for item in text_word if str(item).strip()]

        rec_text = mapping.get("rec_text")
        if isinstance(rec_text, str) and rec_text.strip():
            return [rec_text]

    json_payload = getattr(page, "json", None)
    if isinstance(json_payload, dict):
        return _extract_paddle_page_lines(json_payload.get("res", json_payload))

    if isinstance(page, (list, tuple)):
        legacy_lines: list[str] = []
        for item in page:
            if (
                isinstance(item, (list, tuple))
                and len(item) >= 2
                and isinstance(item[1], (list, tuple))
                and item[1]
            ):
                text_value = str(item[1][0]).strip()
                if text_value:
                    legacy_lines.append(text_value)
        if legacy_lines:
            return legacy_lines

        nested_lines: list[str] = []
        for item in page:
            nested_lines.extend(_extract_paddle_page_lines(item))
        return nested_lines

    return []


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value

    try:
        keys = value.keys()  # type: ignore[attr-defined]
    except Exception:
        return None

    mapping: dict[str, Any] = {}
    for key in keys:
        try:
            mapping[str(key)] = value[key]
        except Exception:
            continue
    return mapping

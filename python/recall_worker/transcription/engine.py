from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any


class TranscriptionEngine:
    engine_name = "none"
    model_name = "none"
    degraded = True

    def transcribe(self, audio_path: Path) -> list[dict[str, int | str]]:
        del audio_path
        return []


class FasterWhisperEngine(TranscriptionEngine):
    engine_name = "faster-whisper"
    model_name = "small"
    degraded = False

    def __init__(self) -> None:
        from faster_whisper import WhisperModel  # type: ignore

        self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: Path) -> list[dict[str, int | str]]:
        segments, _info = self._model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
            language="en",
        )
        results: list[dict[str, int | str]] = []
        for segment in segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            results.append(
                {
                    "startMs": max(0, round(float(segment.start) * 1000)),
                    "endMs": max(0, round(float(segment.end) * 1000)),
                    "text": text,
                }
            )
        return results


class LazyTranscriptionEngine(TranscriptionEngine):
    engine_name = "deferred"
    model_name = "small"
    degraded = False

    def __init__(self) -> None:
        self._engine: TranscriptionEngine | None = None
        self._phase = "deferred"
        self._last_error: str | None = None
        self._last_init_ms: int | None = None
        self._lock = threading.RLock()

    def ensure_ready(self) -> TranscriptionEngine:
        if self._engine is not None:
            return self._engine

        with self._lock:
            if self._engine is not None:
                return self._engine

            self._phase = "warming"
            started = time.perf_counter()
            try:
                engine: TranscriptionEngine = FasterWhisperEngine()
            except Exception as error:
                engine = TranscriptionEngine()
                self._last_error = str(error) or type(error).__name__
            self._last_init_ms = round((time.perf_counter() - started) * 1000)
            self._engine = engine
            self.engine_name = engine.engine_name
            self.model_name = engine.model_name
            self.degraded = engine.degraded
            self._phase = "ready" if engine.engine_name != "none" else "limited"
            return self._engine

    def transcribe(self, audio_path: Path) -> list[dict[str, int | str]]:
        return self.ensure_ready().transcribe(audio_path)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self._phase,
                "engine_name": self.engine_name,
                "model_name": self.model_name,
                "degraded": self.degraded,
                "last_error": self._last_error,
                "last_init_ms": self._last_init_ms,
            }


def create_transcription_engine() -> LazyTranscriptionEngine:
    return LazyTranscriptionEngine()

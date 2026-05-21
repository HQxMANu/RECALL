from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | AUDIO_EXTENSIONS


@dataclass(slots=True)
class AppConfig:
    app_data_dir: Path
    database_path: Path
    thumbnail_dir: Path
    vector_index_path: Path | None = None
    image_vector_index_path: Path | None = None
    text_vector_index_path: Path | None = None
    max_thumbnail_size: int = 320
    search_limit: int = 200

    def __post_init__(self) -> None:
        if self.vector_index_path is None:
            self.vector_index_path = self.app_data_dir / "recall-images.faiss"
        if self.image_vector_index_path is None:
            self.image_vector_index_path = self.vector_index_path
        if self.text_vector_index_path is None:
            self.text_vector_index_path = self.app_data_dir / "recall-text.faiss"


def load_config() -> AppConfig:
    raw_dir = os.environ.get("RECALL_APP_DATA_DIR")
    app_data_dir = Path(raw_dir).expanduser() if raw_dir else Path.cwd() / ".recall-data"
    app_data_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_dir = app_data_dir / "thumbnails"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        app_data_dir=app_data_dir,
        database_path=app_data_dir / "recall.db",
        thumbnail_dir=thumbnail_dir,
        image_vector_index_path=app_data_dir / "recall-images.faiss",
        text_vector_index_path=app_data_dir / "recall-text.faiss",
        vector_index_path=app_data_dir / "recall-images.faiss",
    )

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(slots=True)
class AppConfig:
    app_data_dir: Path
    database_path: Path
    thumbnail_dir: Path
    vector_index_path: Path
    max_thumbnail_size: int = 320
    search_limit: int = 200


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
        vector_index_path=app_data_dir / "recall.faiss",
    )

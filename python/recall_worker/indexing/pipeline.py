from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from recall_worker.core.config import SUPPORTED_EXTENSIONS


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IndexingPipeline:
    def __init__(self, config, database, ocr_engine, embedder, vector_index) -> None:
        self.config = config
        self.database = database
        self.ocr_engine = ocr_engine
        self.embedder = embedder
        self.vector_index = vector_index

    def scan_folder(self, folder_record, progress_callback) -> None:
        folder_path = Path(folder_record["path"])
        candidate_paths = [
            path
            for path in folder_path.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("~")
        ]
        if candidate_paths:
            self.ocr_engine.ensure_ready()

        seen_paths: set[str] = set()
        total = len(candidate_paths)
        for index, image_path in enumerate(candidate_paths, start=1):
            seen_paths.add(str(image_path))
            self.process_image(folder_record["id"], image_path)
            progress_callback(total, index)

        stale_ids = self.database.prune_folder_images(int(folder_record["id"]), seen_paths)
        for image_id in stale_ids:
            self.vector_index.remove(image_id)

    def process_events(self, events: list[dict], indexed_folders: list[dict]) -> None:
        folder_lookup = [(Path(folder["path"]), int(folder["id"])) for folder in indexed_folders]
        if any(
            event["kind"] != "delete" and Path(event["path"]).suffix.lower() in SUPPORTED_EXTENSIONS
            for event in events
        ):
            self.ocr_engine.ensure_ready()
        for event in events:
            path = Path(event["path"])
            if event["kind"] == "delete" or not path.exists():
                removed_id = self.database.delete_image(str(path))
                if removed_id is not None:
                    self.vector_index.remove(removed_id)
                continue

            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            match = next(
                (folder_id for folder_path, folder_id in folder_lookup if folder_path in path.parents or folder_path == path),
                None,
            )
            if match is not None:
                self.process_image(match, path)

    def process_image(self, folder_id: int, image_path: Path) -> None:
        stat = image_path.stat()
        existing = self.database.get_image_by_path(str(image_path))
        if (
            existing
            and existing["modified_at_fs"] == datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            and int(existing["file_size_bytes"]) == stat.st_size
        ):
            return

        content_hash = file_sha256(image_path)
        duplicate = self.database.get_image_by_hash(content_hash)
        timestamp = utcnow_iso()
        width = None
        height = None
        thumbnail_path: Path | None = None
        ocr_text = ""
        warning_code = None
        warning_message = None

        try:
            with Image.open(image_path) as image:
                width, height = image.size
            thumbnail_path = self._ensure_thumbnail(image_path, content_hash)
            if duplicate and duplicate["path"] != str(image_path):
                ocr_text = duplicate["ocr_text"] or ""
                vector = self.database.get_embedding_vector(int(duplicate["id"]))
                if vector is None:
                    vector = self.embedder.embed_image(image_path, f"{image_path.name} {ocr_text}")
            else:
                try:
                    ocr_text = self.ocr_engine.extract_text(image_path)
                except Exception as error:  # noqa: BLE001
                    warning_code = type(error).__name__
                    warning_message = str(error) or type(error).__name__
                    ocr_text = ""
                vector = self.embedder.embed_image(image_path, f"{image_path.name} {ocr_text}")

            payload = {
                "folder_id": folder_id,
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
                "modified_at_fs": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "file_size_bytes": stat.st_size,
                "width": width,
                "height": height,
                "ocr_text": ocr_text,
                "thumbnail_path": str(thumbnail_path) if thumbnail_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "ready",
                "error_code": warning_code,
                "error_message": warning_message,
            }
            image_id = self.database.upsert_image(payload)
            self.database.upsert_embedding(image_id, self.embedder.model_name, ensure_float32(vector), timestamp)
            self.vector_index.upsert(image_id, ensure_float32(vector))
        except Exception as error:  # noqa: BLE001
            payload = {
                "folder_id": folder_id,
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
                "modified_at_fs": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "file_size_bytes": stat.st_size,
                "width": width,
                "height": height,
                "ocr_text": None,
                "thumbnail_path": str(thumbnail_path) if thumbnail_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "error",
                "error_code": type(error).__name__,
                "error_message": str(error) or type(error).__name__,
            }
            self.database.upsert_image(payload)

    def _ensure_thumbnail(self, image_path: Path, content_hash: str) -> Path:
        thumbnail_path = self.config.thumbnail_dir / f"{content_hash}.jpg"
        if thumbnail_path.exists():
            return thumbnail_path
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            image.thumbnail((self.config.max_thumbnail_size, self.config.max_thumbnail_size))
            image.save(thumbnail_path, format="JPEG", quality=85)
        return thumbnail_path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_float32(vector: np.ndarray) -> np.ndarray:
    return vector.astype(np.float32)

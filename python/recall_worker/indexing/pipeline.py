from __future__ import annotations

import os
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image

from recall_worker.core.config import SUPPORTED_EXTENSIONS


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class PreparedImageRecord:
    payload: dict
    vector: np.ndarray | None


class IndexingPipeline:
    chunk_size = 64

    def __init__(self, config, database, ocr_engine, embedder, vector_index) -> None:
        self.config = config
        self.database = database
        self.ocr_engine = ocr_engine
        self.embedder = embedder
        self.vector_index = vector_index

    def scan_folder(self, folder_record, progress_callback) -> None:
        folder_path = Path(folder_record["path"])
        seen_paths: set[str] = set()
        discovered = 0
        ocr_ready = False
        chunk: list[PreparedImageRecord] = []
        for image_path in self._iter_supported_images(folder_path):
            discovered += 1
            if not ocr_ready:
                self.ocr_engine.ensure_ready()
                ocr_ready = True
            seen_paths.add(str(image_path))
            prepared = self.process_image(folder_record["id"], image_path)
            if prepared is not None:
                chunk.append(prepared)
            if len(chunk) >= self.chunk_size:
                self.flush_chunk(chunk)
                chunk.clear()
            progress_callback(discovered, discovered)

        if chunk:
            self.flush_chunk(chunk)
        if discovered == 0:
            progress_callback(0, 0)

        stale_ids = self.database.prune_folder_images(int(folder_record["id"]), seen_paths)
        for image_id in stale_ids:
            self.vector_index.remove(image_id)
        if stale_ids:
            self.vector_index.flush(self.database.get_embeddings_state())

    def process_events(self, events: list[dict], indexed_folders: list[dict]) -> None:
        folder_lookup = [(Path(folder["path"]), int(folder["id"])) for folder in indexed_folders]
        if any(
            event["kind"] != "delete" and Path(event["path"]).suffix.lower() in SUPPORTED_EXTENSIONS
            for event in events
        ):
            self.ocr_engine.ensure_ready()
        chunk: list[PreparedImageRecord] = []
        removed = False
        prepared_count = 0
        flush_count = 0
        max_chunk_len = 0
        started = perf_counter()
        for event in events:
            path = Path(event["path"])
            if event["kind"] == "delete" or not path.exists():
                removed_id = self.database.delete_image(str(path))
                if removed_id is not None:
                    self.vector_index.remove(removed_id)
                    removed = True
                continue

            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            match = next(
                (folder_id for folder_path, folder_id in folder_lookup if folder_path in path.parents or folder_path == path),
                None,
            )
            if match is not None:
                prepared = self.process_image(match, path)
                if prepared is not None:
                    chunk.append(prepared)
                    prepared_count += 1
                    max_chunk_len = max(max_chunk_len, len(chunk))
                    if len(chunk) >= self.chunk_size:
                        self.flush_chunk(chunk)
                        chunk.clear()
                        flush_count += 1

        if chunk:
            self.flush_chunk(chunk)
            flush_count += 1
        if removed:
            self.vector_index.flush(self.database.get_embeddings_state())
        if events:
            duration_ms = round((perf_counter() - started) * 1000)
            print(
                (
                    "Processed fs events: "
                    f"events={len(events)} prepared={prepared_count} removed={int(removed)} "
                    f"flushes={flush_count} max_chunk={max_chunk_len} took={duration_ms}ms"
                ),
                file=sys.stderr,
                flush=True,
            )

    def process_image(self, folder_id: int, image_path: Path) -> PreparedImageRecord | None:
        stat = image_path.stat()
        existing = self.database.get_image_by_path(str(image_path))
        if (
            existing
            and existing["modified_at_fs"] == datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            and int(existing["file_size_bytes"]) == stat.st_size
        ):
            return None

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
                thumbnail_path = self._ensure_thumbnail_from_image(image, content_hash)
                if duplicate and duplicate["path"] != str(image_path):
                    ocr_text = duplicate["ocr_text"] or ""
                    vector = self.database.get_embedding_vector(int(duplicate["id"]))
                    if vector is None:
                        vector = self.embedder.embed_image(image_path, f"{image_path.name} {ocr_text}", image=image)
                else:
                    try:
                        ocr_text = self.ocr_engine.extract_text(image_path)
                    except Exception as error:  # noqa: BLE001
                        warning_code = type(error).__name__
                        warning_message = str(error) or type(error).__name__
                        ocr_text = ""
                    vector = self.embedder.embed_image(image_path, f"{image_path.name} {ocr_text}", image=image)

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
            return PreparedImageRecord(
                payload=payload,
                vector=ensure_float32(vector),
            )
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
            return PreparedImageRecord(payload=payload, vector=None)

    def flush_chunk(self, chunk: list[PreparedImageRecord]) -> None:
        payloads = [record.payload for record in chunk]
        image_ids_by_path = self.database.upsert_images_batch(payloads)

        embedding_records: list[tuple[int, str, np.ndarray, str]] = []
        for record in chunk:
            if record.vector is None:
                continue
            image_id = image_ids_by_path.get(record.payload["path"])
            if image_id is None:
                continue
            embedding_records.append(
                (
                    image_id,
                    self.embedder.model_name,
                    record.vector,
                    record.payload["last_indexed_at"],
                )
            )
            self.vector_index.upsert(image_id, record.vector)

        if embedding_records:
            self.database.upsert_embeddings_batch(embedding_records)
            self.vector_index.flush(self.database.get_embeddings_state())

    def _ensure_thumbnail_from_image(self, image: Image.Image, content_hash: str) -> Path:
        thumbnail_path = self.config.thumbnail_dir / f"{content_hash}.jpg"
        if thumbnail_path.exists():
            return thumbnail_path
        thumbnail = image.convert("RGB")
        thumbnail.thumbnail((self.config.max_thumbnail_size, self.config.max_thumbnail_size))
        thumbnail.save(thumbnail_path, format="JPEG", quality=85)
        return thumbnail_path

    def _iter_supported_images(self, root: Path):
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    sorted_entries = sorted(entries, key=lambda entry: entry.name.lower())
            except OSError:
                continue

            child_dirs: list[Path] = []
            for entry in sorted_entries:
                entry_path = Path(entry.path)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        child_dirs.append(entry_path)
                    elif (
                        entry.is_file(follow_symlinks=False)
                        and entry_path.suffix.lower() in SUPPORTED_EXTENSIONS
                        and not entry_path.name.startswith("~")
                    ):
                        yield entry_path
                except OSError:
                    continue
            for child_dir in reversed(child_dirs):
                stack.append(child_dir)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_float32(vector: np.ndarray) -> np.ndarray:
    return vector.astype(np.float32)

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image

from recall_worker.core.config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS
from recall_worker.indexing.content import extract_audio_chunks, extract_document_chunks, render_document_preview


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class PreparedTextChunk:
    chunk_index: int
    chunk_type: str
    chunk_text: str
    vector: np.ndarray | None
    page_number: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(slots=True)
class PreparedAssetRecord:
    asset_payload: dict
    asset_type: str
    image_payload: dict | None = None
    image_vector: np.ndarray | None = None
    text_chunks: list[PreparedTextChunk] = field(default_factory=list)


class IndexingPipeline:
    chunk_size = 64
    watcher_log_event_threshold = 16
    watcher_log_duration_ms = 400

    def __init__(
        self,
        config,
        database,
        ocr_engine,
        image_embedder,
        text_embedder=None,
        image_vector_index=None,
        text_vector_index=None,
        transcription_engine=None,
    ) -> None:
        if image_vector_index is None and text_embedder is not None:
            image_vector_index = text_embedder
            text_embedder = image_embedder
        if text_embedder is None:
            text_embedder = image_embedder
        if text_vector_index is None:
            text_vector_index = image_vector_index
        if transcription_engine is None:
            transcription_engine = _NoopTranscriptionEngine()
        self.config = config
        self.database = database
        self.ocr_engine = ocr_engine
        self.image_embedder = image_embedder
        self.text_embedder = text_embedder
        self.image_vector_index = image_vector_index
        self.text_vector_index = text_vector_index
        self.transcription_engine = transcription_engine

    def scan_folder(self, folder_record, progress_callback) -> None:
        folder_path = Path(folder_record["path"])
        seen_paths: set[str] = set()
        discovered = 0
        ocr_ready = False
        chunk: list[PreparedAssetRecord] = []
        for asset_path in self._iter_supported_files(folder_path):
            discovered += 1
            if asset_path.suffix.lower() in IMAGE_EXTENSIONS and not ocr_ready:
                self.ocr_engine.ensure_ready()
                ocr_ready = True
            seen_paths.add(str(asset_path))
            prepared = self.process_asset(folder_record["id"], asset_path)
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

        stale = self.database.prune_folder_assets(int(folder_record["id"]), seen_paths)
        for image_id in stale["imageIds"]:
            self.image_vector_index.remove(image_id)
        for chunk_id in stale["textChunkIds"]:
            self.text_vector_index.remove(chunk_id)
        if stale["imageIds"]:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if stale["textChunkIds"]:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())

    def process_events(self, events: list[dict], indexed_folders: list[dict]) -> None:
        folder_lookup = {
            self._normalize_path(Path(folder["path"])): int(folder["id"])
            for folder in indexed_folders
        }
        if any(
            event["kind"] != "delete" and Path(event["path"]).suffix.lower() in IMAGE_EXTENSIONS
            for event in events
        ):
            self.ocr_engine.ensure_ready()
        chunk: list[PreparedAssetRecord] = []
        removed_image = False
        removed_text = False
        prepared_count = 0
        flush_count = 0
        max_chunk_len = 0
        started = perf_counter()
        for event in events:
            path = Path(event["path"])
            if event["kind"] == "delete" or not path.exists():
                deleted = self.database.delete_path(str(path))
                for image_id in deleted["imageIds"]:
                    self.image_vector_index.remove(image_id)
                    removed_image = True
                for chunk_id in deleted["textChunkIds"]:
                    self.text_vector_index.remove(chunk_id)
                    removed_text = True
                continue

            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            match = self._match_folder_id(path, folder_lookup)
            if match is None:
                continue

            prepared = self.process_asset(match, path)
            if prepared is None:
                continue
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
        if removed_image:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if removed_text:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())
        if events:
            duration_ms = round((perf_counter() - started) * 1000)
            should_log = (
                len(events) >= self.watcher_log_event_threshold
                or flush_count > 1
                or removed_image
                or removed_text
                or duration_ms >= self.watcher_log_duration_ms
            )
            if should_log:
                print(
                    (
                        "Processed fs events: "
                        f"events={len(events)} prepared={prepared_count} removedImages={int(removed_image)} "
                        f"removedText={int(removed_text)} flushes={flush_count} "
                        f"max_chunk={max_chunk_len} took={duration_ms}ms"
                    ),
                    file=sys.stderr,
                    flush=True,
                )

    def process_asset(self, folder_id: int, asset_path: Path) -> PreparedAssetRecord | None:
        stat = asset_path.stat()
        existing = self.database.get_asset_by_path(str(asset_path))
        modified_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        created_iso = datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
        existing_preview_ready = True
        if existing and existing["asset_type"] == "document":
            preview_path = existing["preview_path"]
            existing_preview_ready = bool(preview_path) and Path(str(preview_path)).exists()
        if (
            existing
            and existing["index_status"] == "ready"
            and existing["modified_at_fs"] == modified_iso
            and int(existing["file_size_bytes"]) == stat.st_size
            and existing_preview_ready
        ):
            return None

        if asset_path.suffix.lower() in IMAGE_EXTENSIONS:
            return self._process_image(folder_id, asset_path, stat, created_iso, modified_iso)
        if asset_path.suffix.lower() in AUDIO_EXTENSIONS:
            return self._process_audio(folder_id, asset_path, stat, created_iso, modified_iso)
        return self._process_document(folder_id, asset_path, stat, created_iso, modified_iso)

    def flush_chunk(self, chunk: list[PreparedAssetRecord]) -> None:
        image_payloads = [record.image_payload for record in chunk if record.image_payload is not None]
        image_ids_by_path = self.database.upsert_images_batch(image_payloads) if image_payloads else {}

        non_image_payloads = [
            record.asset_payload
            for record in chunk
            if record.asset_type != "image"
        ]
        asset_ids_by_path = self.database.upsert_assets_batch(non_image_payloads) if non_image_payloads else {}

        for record in chunk:
            if record.asset_type == "image":
                asset_row = self.database.get_asset_by_path(record.asset_payload["path"])
                if asset_row is not None:
                    asset_ids_by_path[record.asset_payload["path"]] = int(asset_row["id"])

        image_embedding_records: list[tuple[int, str, np.ndarray, str]] = []
        text_embedding_records: list[tuple[int, str, np.ndarray, str]] = []
        text_index_changed = False

        for record in chunk:
            asset_id = asset_ids_by_path.get(record.asset_payload["path"])
            if asset_id is None:
                continue

            removed_chunk_ids, inserted_chunks = self.database.replace_asset_chunks(
                asset_id,
                record.asset_payload["filename"],
                record.asset_payload["path"],
                [
                    {
                        "chunkIndex": chunk_record.chunk_index,
                        "chunkType": chunk_record.chunk_type,
                        "chunkText": chunk_record.chunk_text,
                        "pageNumber": chunk_record.page_number,
                        "startMs": chunk_record.start_ms,
                        "endMs": chunk_record.end_ms,
                    }
                    for chunk_record in record.text_chunks
                ],
            )
            for chunk_id in removed_chunk_ids:
                self.text_vector_index.remove(chunk_id)
                text_index_changed = True

            for (chunk_id, _chunk_payload), chunk_record in zip(inserted_chunks, record.text_chunks, strict=False):
                if chunk_record.vector is None:
                    continue
                text_embedding_records.append(
                    (
                        chunk_id,
                        self.text_embedder.model_name,
                        chunk_record.vector,
                        record.asset_payload["last_indexed_at"],
                    )
                )
                self.text_vector_index.upsert(chunk_id, chunk_record.vector)
                text_index_changed = True

            if record.image_payload is not None and record.image_vector is not None:
                image_id = image_ids_by_path.get(record.image_payload["path"])
                if image_id is not None:
                    image_embedding_records.append(
                        (
                            image_id,
                            self.image_embedder.model_name,
                            record.image_vector,
                            record.asset_payload["last_indexed_at"],
                        )
                    )
                    self.image_vector_index.upsert(image_id, record.image_vector)

        if image_embedding_records:
            self.database.upsert_embeddings_batch(image_embedding_records)
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if text_embedding_records:
            self.database.upsert_text_embeddings_batch(text_embedding_records)
        if text_embedding_records or text_index_changed:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())

    def _process_image(self, folder_id: int, image_path: Path, stat, created_iso: str, modified_iso: str) -> PreparedAssetRecord:
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
                        vector = self.image_embedder.embed_image(image_path, f"{image_path.name} {ocr_text}", image=image)
                else:
                    try:
                        ocr_text = self.ocr_engine.extract_text(image_path)
                    except Exception as error:  # noqa: BLE001
                        warning_code = type(error).__name__
                        warning_message = str(error) or type(error).__name__
                        ocr_text = ""
                    vector = self.image_embedder.embed_image(image_path, f"{image_path.name} {ocr_text}", image=image)

            payload = {
                "folder_id": folder_id,
                "asset_type": "image",
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": width,
                "height": height,
                "duration_ms": None,
                "preview_path": str(thumbnail_path) if thumbnail_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "ready",
                "error_code": warning_code,
                "error_message": warning_message,
            }
            image_payload = {
                "folder_id": folder_id,
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
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
            text_chunks = self._text_chunks_from_text(ocr_text, chunk_type="ocr")
            return PreparedAssetRecord(
                asset_payload=payload,
                asset_type="image",
                image_payload=image_payload,
                image_vector=ensure_float32(vector),
                text_chunks=text_chunks,
            )
        except Exception as error:  # noqa: BLE001
            payload = {
                "folder_id": folder_id,
                "asset_type": "image",
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": width,
                "height": height,
                "duration_ms": None,
                "preview_path": str(thumbnail_path) if thumbnail_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "error",
                "error_code": type(error).__name__,
                "error_message": str(error) or type(error).__name__,
            }
            image_payload = {
                "folder_id": folder_id,
                "path": str(image_path),
                "filename": image_path.name,
                "extension": image_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
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
            return PreparedAssetRecord(asset_payload=payload, asset_type="image", image_payload=image_payload)

    def _process_document(self, folder_id: int, document_path: Path, stat, created_iso: str, modified_iso: str) -> PreparedAssetRecord:
        content_hash = file_sha256(document_path)
        timestamp = utcnow_iso()
        warning_code = None
        warning_message = None
        preview_path: Path | None = None
        try:
            chunks, extraction_mode = extract_document_chunks(document_path, self.ocr_engine)
            if extraction_mode == "ocr_fallback":
                warning_code = "ocr_fallback"
                warning_message = "PDF text extraction was weak; OCR fallback was used."
            preview_path = self._ensure_document_preview(document_path, content_hash, chunks)
            text_chunks = [
                PreparedTextChunk(
                    chunk_index=chunk.chunk_index,
                    chunk_type=chunk.chunk_type,
                    chunk_text=chunk.text,
                    vector=ensure_float32(self.text_embedder.embed_text(chunk.text)),
                    page_number=chunk.page_number,
                )
                for chunk in chunks
            ]
            payload = {
                "folder_id": folder_id,
                "asset_type": "document",
                "path": str(document_path),
                "filename": document_path.name,
                "extension": document_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": None,
                "height": None,
                "duration_ms": None,
                "preview_path": str(preview_path) if preview_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "ready",
                "error_code": warning_code,
                "error_message": warning_message,
            }
            return PreparedAssetRecord(asset_payload=payload, asset_type="document", text_chunks=text_chunks)
        except Exception as error:  # noqa: BLE001
            payload = {
                "folder_id": folder_id,
                "asset_type": "document",
                "path": str(document_path),
                "filename": document_path.name,
                "extension": document_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": None,
                "height": None,
                "duration_ms": None,
                "preview_path": str(preview_path) if preview_path is not None else None,
                "last_indexed_at": timestamp,
                "index_status": "error",
                "error_code": type(error).__name__,
                "error_message": str(error) or type(error).__name__,
            }
            return PreparedAssetRecord(asset_payload=payload, asset_type="document")

    def _process_audio(self, folder_id: int, audio_path: Path, stat, created_iso: str, modified_iso: str) -> PreparedAssetRecord:
        content_hash = file_sha256(audio_path)
        timestamp = utcnow_iso()
        try:
            chunks, duration_ms = extract_audio_chunks(audio_path, self.transcription_engine)
            text_chunks = [
                PreparedTextChunk(
                    chunk_index=chunk.chunk_index,
                    chunk_type=chunk.chunk_type,
                    chunk_text=chunk.text,
                    vector=ensure_float32(self.text_embedder.embed_text(chunk.text)),
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                )
                for chunk in chunks
            ]
            payload = {
                "folder_id": folder_id,
                "asset_type": "voice-note",
                "path": str(audio_path),
                "filename": audio_path.name,
                "extension": audio_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": None,
                "height": None,
                "duration_ms": duration_ms,
                "preview_path": None,
                "last_indexed_at": timestamp,
                "index_status": "ready",
                "error_code": None,
                "error_message": None,
            }
            return PreparedAssetRecord(asset_payload=payload, asset_type="voice-note", text_chunks=text_chunks)
        except Exception as error:  # noqa: BLE001
            payload = {
                "folder_id": folder_id,
                "asset_type": "voice-note",
                "path": str(audio_path),
                "filename": audio_path.name,
                "extension": audio_path.suffix.lower(),
                "content_hash": content_hash,
                "created_at_fs": created_iso,
                "modified_at_fs": modified_iso,
                "file_size_bytes": stat.st_size,
                "width": None,
                "height": None,
                "duration_ms": None,
                "preview_path": None,
                "last_indexed_at": timestamp,
                "index_status": "error",
                "error_code": type(error).__name__,
                "error_message": str(error) or type(error).__name__,
            }
            return PreparedAssetRecord(asset_payload=payload, asset_type="voice-note")

    def _text_chunks_from_text(self, text: str, *, chunk_type: str) -> list[PreparedTextChunk]:
        normalized = (text or "").strip()
        if not normalized or not hasattr(self.text_embedder, "embed_text"):
            return []
        return [
            PreparedTextChunk(
                chunk_index=0,
                chunk_type=chunk_type,
                chunk_text=normalized,
                vector=ensure_float32(self.text_embedder.embed_text(normalized)),
            )
        ]

    def _ensure_thumbnail_from_image(self, image: Image.Image, content_hash: str) -> Path:
        thumbnail_path = self.config.thumbnail_dir / f"{content_hash}.jpg"
        if thumbnail_path.exists():
            return thumbnail_path
        thumbnail = image.convert("RGB")
        thumbnail.thumbnail((self.config.max_thumbnail_size, self.config.max_thumbnail_size))
        thumbnail.save(thumbnail_path, format="JPEG", quality=85)
        return thumbnail_path

    def _ensure_document_preview(
        self,
        document_path: Path,
        content_hash: str,
        chunks,
    ) -> Path:
        preview_path = self.config.thumbnail_dir / f"{content_hash}-document.jpg"
        return render_document_preview(
            document_path,
            preview_path,
            max_size=self.config.max_thumbnail_size * 2,
            chunks=chunks,
        )

    def _iter_supported_files(self, root: Path):
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

    @staticmethod
    def _normalize_path(path: Path) -> str:
        candidate = path.expanduser()
        try:
            normalized = candidate.resolve(strict=False)
        except OSError:
            normalized = candidate.absolute()
        return str(normalized)

    def _match_folder_id(self, path: Path, folder_lookup: dict[str, int]) -> int | None:
        current = path
        while True:
            folder_id = folder_lookup.get(self._normalize_path(current))
            if folder_id is not None:
                return folder_id
            parent = current.parent
            if parent == current:
                return None
            current = parent


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_float32(vector: np.ndarray) -> np.ndarray:
    return vector.astype(np.float32)


class _NoopTranscriptionEngine:
    def transcribe(self, _audio_path: Path) -> list[dict[str, int | str]]:
        return []

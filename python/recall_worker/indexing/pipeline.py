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
from recall_worker.indexing.content import (
    extract_audio_chunks,
    extract_document_chunks,
    normalize_image_orientation,
    render_document_preview,
)


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
        self._ocr_ready = False

    def scan_folder(self, folder_record, progress_callback, *, force_reprocess: bool = False) -> None:
        folder_path = Path(folder_record["path"])
        seen_paths: set[str] = set()
        discovered = 0
        chunk: list[PreparedAssetRecord] = []
        image_index_changed = False
        text_index_changed = False
        for asset_path in self._iter_supported_files(folder_path):
            discovered += 1
            seen_paths.add(str(asset_path))
            prepared = self.process_asset(
                folder_record["id"],
                asset_path,
                force_reprocess=force_reprocess,
            )
            if prepared is not None:
                chunk.append(prepared)
            if len(chunk) >= self.chunk_size:
                chunk_image_changed, chunk_text_changed = self.flush_chunk(chunk, flush_vectors=False)
                image_index_changed = image_index_changed or chunk_image_changed
                text_index_changed = text_index_changed or chunk_text_changed
                chunk.clear()
            progress_callback(discovered, discovered)

        if chunk:
            chunk_image_changed, chunk_text_changed = self.flush_chunk(chunk, flush_vectors=False)
            image_index_changed = image_index_changed or chunk_image_changed
            text_index_changed = text_index_changed or chunk_text_changed
        if discovered == 0:
            progress_callback(0, 0)

        stale = self.database.prune_folder_assets(int(folder_record["id"]), seen_paths)
        for image_id in stale["imageIds"]:
            self.image_vector_index.remove(image_id)
            image_index_changed = True
        for chunk_id in stale["textChunkIds"]:
            self.text_vector_index.remove(chunk_id)
            text_index_changed = True
        if image_index_changed:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if text_index_changed:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())

    def process_events(self, events: list[dict], indexed_folders: list[dict]) -> None:
        folder_lookup = {
            self._normalize_path(Path(folder["path"])): int(folder["id"])
            for folder in indexed_folders
        }
        folder_records_by_id = {
            int(folder["id"]): folder
            for folder in indexed_folders
        }
        active_folder_ids = set(folder_records_by_id)
        chunk: list[PreparedAssetRecord] = []
        removed_image = False
        removed_text = False
        image_index_changed = False
        text_index_changed = False
        prepared_count = 0
        flush_count = 0
        max_chunk_len = 0
        reconciled_folder_ids: set[int] = set()
        requires_global_reconcile = False
        requires_fallback_reconcile = False
        started = perf_counter()
        for event in events:
            path = Path(event["path"])
            folder_match = self._match_folder_id(path, folder_lookup)
            if event["kind"] == "delete" or not path.exists():
                deleted = self.database.delete_path(str(path))
                for image_id in deleted["imageIds"]:
                    self.image_vector_index.remove(image_id)
                    removed_image = True
                for chunk_id in deleted["textChunkIds"]:
                    self.text_vector_index.remove(chunk_id)
                    removed_text = True
                if folder_match is not None:
                    if len(active_folder_ids) > 1:
                        # A delete event inside one indexed folder can actually
                        # represent a move into a different indexed folder when
                        # the watcher only reports the source path. Reconcile
                        # all indexed folders so the asset can be rediscovered
                        # at its new location.
                        requires_global_reconcile = True
                    else:
                        reconciled_folder_ids.add(folder_match)
                continue

            if path.is_dir():
                if folder_match is not None:
                    reconciled_folder_ids.add(folder_match)
                continue

            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                if folder_match is not None:
                    reconciled_folder_ids.add(folder_match)
                continue

            if folder_match is None:
                continue

            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                # Document and audio writes often arrive through temp-file or
                # cloud-sync flows where the final file contents/path settle
                # after the first watcher event. Reconcile the whole folder so
                # the finished asset state on disk is what gets indexed.
                reconciled_folder_ids.add(folder_match)
                continue

            prepared = self.process_asset(folder_match, path)
            if prepared is None:
                continue
            chunk.append(prepared)
            prepared_count += 1
            max_chunk_len = max(max_chunk_len, len(chunk))
            if len(chunk) >= self.chunk_size:
                chunk_image_changed, chunk_text_changed = self.flush_chunk(chunk, flush_vectors=False)
                image_index_changed = image_index_changed or chunk_image_changed
                text_index_changed = text_index_changed or chunk_text_changed
                chunk.clear()
                flush_count += 1

        if chunk:
            chunk_image_changed, chunk_text_changed = self.flush_chunk(chunk, flush_vectors=False)
            image_index_changed = image_index_changed or chunk_image_changed
            text_index_changed = text_index_changed or chunk_text_changed
            flush_count += 1
        if (
            events
            and not prepared_count
            and not removed_image
            and not removed_text
            and not reconciled_folder_ids
            and active_folder_ids
        ):
            # Some desktop/cloud-sync flows emit watcher events that point to
            # transient paths or produce no direct file-level delta even though
            # the indexed folders have changed. Fall back to a full active-folder
            # reconcile so new supported assets are rediscovered instead of
            # silently missing from search.
            requires_fallback_reconcile = True
        if requires_global_reconcile:
            reconciled_folder_ids.update(active_folder_ids)
        if requires_fallback_reconcile:
            reconciled_folder_ids.update(active_folder_ids)
        for folder_id in sorted(reconciled_folder_ids):
            folder_record = folder_records_by_id.get(folder_id)
            if folder_record is None:
                continue
            self.scan_folder(folder_record, lambda total, processed: None)
        if removed_image or image_index_changed:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if removed_text or text_index_changed:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())
        if events:
            duration_ms = round((perf_counter() - started) * 1000)
            should_log = (
                len(events) >= self.watcher_log_event_threshold
                or flush_count > 1
                or removed_image
                or removed_text
                or bool(reconciled_folder_ids)
                or requires_global_reconcile
                or duration_ms >= self.watcher_log_duration_ms
            )
            if should_log:
                print(
                    (
                        "Processed fs events: "
                        f"events={len(events)} prepared={prepared_count} removedImages={int(removed_image)} "
                        f"removedText={int(removed_text)} flushes={flush_count} "
                        f"globalReconcile={int(requires_global_reconcile)} "
                        f"fallbackReconcile={int(requires_fallback_reconcile)} "
                        f"reconciledFolders={len(reconciled_folder_ids)} "
                        f"max_chunk={max_chunk_len} took={duration_ms}ms"
                    ),
                    file=sys.stderr,
                    flush=True,
                )

    def process_asset(
        self,
        folder_id: int,
        asset_path: Path,
        *,
        force_reprocess: bool = False,
    ) -> PreparedAssetRecord | None:
        stat = asset_path.stat()
        existing = self.database.get_asset_by_path(str(asset_path))
        modified_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        created_iso = datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
        existing_metadata_matches = (
            existing
            and existing["modified_at_fs"] == modified_iso
            and int(existing["file_size_bytes"]) == stat.st_size
        )
        content_hash: str | None = None
        existing_content_hash = str(existing["content_hash"]) if existing and existing["content_hash"] else None

        if not force_reprocess and existing_metadata_matches:
            if existing["index_status"] == "ready" and existing_content_hash and self._existing_preview_ready(existing):
                return None

            if existing["index_status"] == "ready" and existing["asset_type"] == "image":
                content_hash = file_sha256(asset_path)
                if existing_content_hash != content_hash:
                    existing_metadata_matches = False
                elif self._repair_missing_image_thumbnail(existing, asset_path, content_hash):
                    return None

        if content_hash is None and (force_reprocess or not existing_metadata_matches or not existing_content_hash):
            content_hash = file_sha256(asset_path)

        if (
            not force_reprocess
            and existing_metadata_matches
            and existing_content_hash
            and existing["index_status"] == "ready"
            and existing["asset_type"] == "image"
        ):
            if content_hash is None:
                content_hash = file_sha256(asset_path)
            if existing_content_hash == content_hash:
                if self._repair_missing_image_thumbnail(existing, asset_path, content_hash):
                    return None

        if asset_path.suffix.lower() in IMAGE_EXTENSIONS:
            return self._process_image(
                folder_id,
                asset_path,
                stat,
                created_iso,
                modified_iso,
                force_reprocess=force_reprocess,
                content_hash=content_hash,
            )
        if asset_path.suffix.lower() in AUDIO_EXTENSIONS:
            return self._process_audio(folder_id, asset_path, stat, created_iso, modified_iso, content_hash=content_hash)
        return self._process_document(folder_id, asset_path, stat, created_iso, modified_iso, content_hash=content_hash)

    def flush_chunk(
        self,
        chunk: list[PreparedAssetRecord],
        *,
        flush_vectors: bool = True,
    ) -> tuple[bool, bool]:
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
        image_vector_records: list[tuple[int, np.ndarray]] = []
        text_vector_records: list[tuple[int, np.ndarray]] = []
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
                text_vector_records.append((chunk_id, chunk_record.vector))
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
                    image_vector_records.append((image_id, record.image_vector))

        if image_vector_records:
            self.image_vector_index.upsert_many(image_vector_records)
        if text_vector_records:
            self.text_vector_index.upsert_many(text_vector_records)
        if image_embedding_records:
            self.database.upsert_embeddings_batch(image_embedding_records)
        if text_embedding_records:
            self.database.upsert_text_embeddings_batch(text_embedding_records)
        image_index_changed = bool(image_embedding_records)
        text_index_changed = bool(text_embedding_records) or text_index_changed
        if flush_vectors and image_index_changed:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if flush_vectors and text_index_changed:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())
        return image_index_changed, text_index_changed

    def _process_image(
        self,
        folder_id: int,
        image_path: Path,
        stat,
        created_iso: str,
        modified_iso: str,
        *,
        force_reprocess: bool = False,
        content_hash: str | None = None,
    ) -> PreparedAssetRecord:
        content_hash = content_hash or file_sha256(image_path)
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
                normalized_image = normalize_image_orientation(image)
                try:
                    width, height = normalized_image.size
                    thumbnail_path = self._ensure_thumbnail_from_image(
                        normalized_image,
                        content_hash,
                        force=force_reprocess,
                    )
                    if duplicate and duplicate["path"] != str(image_path):
                        ocr_text = duplicate["ocr_text"] or ""
                        vector = self.database.get_embedding_vector(int(duplicate["id"]))
                        if vector is None:
                            vector = self.image_embedder.embed_image(
                                image_path,
                                f"{image_path.name} {ocr_text}",
                                image=normalized_image,
                            )
                    else:
                        try:
                            self._ensure_ocr_ready()
                            ocr_text = self.ocr_engine.extract_text(image_path)
                        except Exception as error:  # noqa: BLE001
                            warning_code = type(error).__name__
                            warning_message = str(error) or type(error).__name__
                            ocr_text = ""
                        vector = self.image_embedder.embed_image(
                            image_path,
                            f"{image_path.name} {ocr_text}",
                            image=normalized_image,
                        )
                finally:
                    if normalized_image is not image:
                        normalized_image.close()

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

    def _process_document(
        self,
        folder_id: int,
        document_path: Path,
        stat,
        created_iso: str,
        modified_iso: str,
        *,
        content_hash: str | None = None,
    ) -> PreparedAssetRecord:
        content_hash = content_hash or file_sha256(document_path)
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

    def _process_audio(
        self,
        folder_id: int,
        audio_path: Path,
        stat,
        created_iso: str,
        modified_iso: str,
        *,
        content_hash: str | None = None,
    ) -> PreparedAssetRecord:
        content_hash = content_hash or file_sha256(audio_path)
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

    def _existing_preview_ready(self, existing) -> bool:
        if existing["asset_type"] == "voice-note":
            return True
        preview_path = existing["preview_path"]
        return bool(preview_path) and Path(str(preview_path)).exists()

    def _repair_missing_image_thumbnail(
        self,
        existing,
        image_path: Path,
        content_hash: str | None,
    ) -> bool:
        if not content_hash:
            return False
        image_row = self.database.get_image_by_path(str(image_path))
        if image_row is None:
            return False

        try:
            with Image.open(image_path) as image:
                normalized_image = normalize_image_orientation(image)
                try:
                    thumbnail_path = self._ensure_thumbnail_from_image(normalized_image, content_hash)
                finally:
                    if normalized_image is not image:
                        normalized_image.close()
            self.database.update_image_preview(
                int(image_row["id"]),
                int(existing["id"]),
                str(thumbnail_path),
                utcnow_iso(),
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def _ensure_thumbnail_from_image(self, image: Image.Image, content_hash: str, *, force: bool = False) -> Path:
        thumbnail_path = self.config.thumbnail_dir / f"{content_hash}.jpg"
        if thumbnail_path.exists() and not force:
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

    def _ensure_ocr_ready(self) -> None:
        if self._ocr_ready:
            return
        self.ocr_engine.ensure_ready()
        self._ocr_ready = True

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

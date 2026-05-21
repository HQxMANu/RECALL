from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from recall_worker.core.config import load_config
from recall_worker.db.database import Database
from recall_worker.embeddings.engine import create_image_embedder, create_text_embedder
from recall_worker.indexing.content import TextChunk, render_document_preview
from recall_worker.indexing.pipeline import IndexingPipeline, utcnow_iso
from recall_worker.ocr.engine import create_ocr_engine
from recall_worker.search.service import SearchService
from recall_worker.search.vector_index import create_vector_index
from recall_worker.transcription.engine import create_transcription_engine

create_embedder = create_image_embedder


@dataclass(slots=True)
class RuntimeStatus:
    state: str = "idle"
    active_job_id: int | None = None
    active_job_type: str | None = None
    items_total: int = 0
    items_processed: int = 0
    queued_jobs: int = 0
    last_completed_at: str | None = None
    last_error: str | None = None


class RecallWorker:
    def __init__(self) -> None:
        startup_started = time.perf_counter()
        self.config = load_config()
        database_started = time.perf_counter()
        self.database = Database(self.config.database_path)
        self.database.recover_running_jobs(
            utcnow_iso(),
            "Recall restarted before the previous indexing job finished.",
        )
        database_ready_ms = round((time.perf_counter() - database_started) * 1000)
        self.ocr_engine = create_ocr_engine()
        self.transcription_engine = create_transcription_engine()

        image_embedding_started = time.perf_counter()
        self.image_embedder = create_image_embedder()
        image_embedding_init_ms = round((time.perf_counter() - image_embedding_started) * 1000)

        text_embedding_started = time.perf_counter()
        self.text_embedder = create_text_embedder()
        text_embedding_init_ms = round((time.perf_counter() - text_embedding_started) * 1000)

        image_vector_started = time.perf_counter()
        image_vector_index_path = getattr(
            self.config,
            "image_vector_index_path",
            getattr(self.config, "vector_index_path"),
        )
        self.image_vector_index = create_vector_index(
            self.image_embedder.dimension,
            image_vector_index_path,
        )
        image_embeddings_state = self.database.get_embeddings_state()
        image_rebuild_batch_count = 0
        if not self.image_vector_index.bootstrap(metadata=image_embeddings_state):
            image_rebuild_batch_count = self._rebuild_image_vector_index_from_batches(image_embeddings_state)
        image_vector_bootstrap_ms = round((time.perf_counter() - image_vector_started) * 1000)

        text_vector_started = time.perf_counter()
        text_vector_index_path = getattr(
            self.config,
            "text_vector_index_path",
            Path(str(image_vector_index_path)).with_name("recall-text.faiss"),
        )
        self.text_vector_index = create_vector_index(
            self.text_embedder.dimension,
            text_vector_index_path,
        )
        text_rebuild_batch_count = 0
        if hasattr(self.database, "get_text_embeddings_state"):
            text_embeddings_state = self.database.get_text_embeddings_state()
            if not self.text_vector_index.bootstrap(metadata=text_embeddings_state):
                text_rebuild_batch_count = self._rebuild_text_vector_index_from_batches(text_embeddings_state)
        else:
            text_embeddings_state = {
                "revision": 0,
                "count": 0,
                "model_name": self.text_embedder.model_name,
                "vector_dim": self.text_embedder.dimension,
            }
        text_vector_bootstrap_ms = round((time.perf_counter() - text_vector_started) * 1000)

        if getattr(self.image_vector_index, "bootstrap_mode", None) == "rebuilt":
            print(
                f"Rebuilt image vector index from streamed batches ({image_rebuild_batch_count} batches).",
                file=sys.stderr,
                flush=True,
            )
        if getattr(self.text_vector_index, "bootstrap_mode", None) == "rebuilt":
            print(
                f"Rebuilt text vector index from streamed batches ({text_rebuild_batch_count} batches).",
                file=sys.stderr,
                flush=True,
            )

        self.pipeline = IndexingPipeline(
            self.config,
            self.database,
            self.ocr_engine,
            self.image_embedder,
            self.text_embedder,
            self.image_vector_index,
            self.text_vector_index,
            self.transcription_engine,
        )
        self.search_service = SearchService(
            self.database,
            self.image_embedder,
            self.text_embedder,
            self.image_vector_index,
            self.text_vector_index,
            self.config.search_limit,
        )
        self.status = RuntimeStatus()
        self._status_lock = threading.RLock()
        self._health_lock = threading.RLock()
        self._scheduler_condition = threading.Condition()
        self._full_index_jobs: list[dict] = []
        self._active_full_index_folder_ids: set[int] = set()
        self._pending_fs_events: dict[str, dict] = {}
        self._shutdown_requested = False
        self._scheduler_metrics = {
            "mergedFsEvents": 0,
            "coalescedFsEvents": 0,
            "dispatchedFsEvents": 0,
            "mergedFullIndexJobs": 0,
            "dedupedFullIndexJobs": 0,
        }
        self._job_thread = threading.Thread(target=self._job_loop, daemon=True, name="recall-indexer")
        self._job_thread.start()
        self._preview_backfill_thread = threading.Thread(
            target=self._repair_missing_document_previews,
            daemon=True,
            name="recall-document-preview-backfill",
        )
        self._preview_backfill_thread.start()
        self._startup_metrics = {
            "databaseReadyMs": database_ready_ms,
            "embeddingInitMs": image_embedding_init_ms + text_embedding_init_ms,
            "vectorBootstrapMs": image_vector_bootstrap_ms + text_vector_bootstrap_ms,
            "coreSearchReadyMs": round((time.perf_counter() - startup_started) * 1000),
            "vectorBootstrapMode": (
                f"images:{getattr(self.image_vector_index, 'bootstrap_mode', 'unknown')},"
                f"text:{getattr(self.text_vector_index, 'bootstrap_mode', 'unknown')}"
            ),
        }
        self._cached_health = self._compute_health_snapshot()
        print(
            (
                "Core search ready in "
                f"{self._startup_metrics['coreSearchReadyMs']} ms "
                f"(image embedder {image_embedding_init_ms} ms, text embedder {text_embedding_init_ms} ms, "
                f"image vector {image_vector_bootstrap_ms} ms, text vector {text_vector_bootstrap_ms} ms)"
            ),
            file=sys.stderr,
            flush=True,
        )

    def add_folders(self, params: dict) -> dict:
        paths = params.get("paths") or []
        canonical_paths: list[str] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            if path.exists() and path.is_dir():
                canonical_paths.append(str(path.resolve()))
        added, skipped = self.database.add_or_reactivate_folders(canonical_paths, utcnow_iso())
        folder_ids = [folder["id"] for folder in added]
        if folder_ids:
            self._enqueue("full_index", {"folderIds": folder_ids, "triggerSource": "user"})
        return {"addedFolders": added, "skippedPaths": skipped}

    def list_folders(self, params: dict | None = None) -> list[dict]:
        del params
        return self.database.list_folders()

    def remove_folder(self, params: dict) -> dict:
        folder_id = int(params["folderId"])
        removed = self.database.delete_folder(folder_id)
        for image_id in removed["imageIds"]:
            self.image_vector_index.remove(image_id)
        for chunk_id in removed["textChunkIds"]:
            self.text_vector_index.remove(chunk_id)
        if removed["imageIds"]:
            self.image_vector_index.flush(self.database.get_embeddings_state())
        if removed["textChunkIds"]:
            self.text_vector_index.flush(self.database.get_text_embeddings_state())
        return removed

    def process_fs_events(self, params: dict) -> dict:
        self._enqueue("fs_events", {"events": params.get("events") or [], "triggerSource": "watcher"})
        return {"queued": True}

    def rebuild_index(self, params: dict) -> dict:
        folder_ids = params.get("folderIds") or [folder["id"] for folder in self.database.list_folders()]
        self._enqueue("full_index", {"folderIds": folder_ids, "triggerSource": "manual_rebuild"})
        return {"queued": True}

    def search(self, params: dict) -> dict:
        return self.search_service.search(params.get("request") or {})

    def search_assets(self, params: dict) -> dict:
        return self.search(params)

    def get_status(self, params: dict | None = None) -> dict:
        del params
        with self._status_lock:
            return {
                "state": self.status.state,
                "activeJobId": self.status.active_job_id,
                "activeJobType": self.status.active_job_type,
                "itemsTotal": self.status.items_total,
                "itemsProcessed": self.status.items_processed,
                "queuedJobs": self._queued_jobs_count(),
                "lastCompletedAt": self.status.last_completed_at,
                "lastError": self.status.last_error,
            }

    def get_health(self, params: dict | None = None) -> dict:
        del params
        with self._health_lock:
            return dict(self._cached_health)

    def _compute_health_snapshot(self) -> dict:
        ocr_status = self.ocr_engine.status()
        transcription_status = self.transcription_engine.status()
        image_vector_ready = self.image_vector_index.engine_name == "faiss"
        text_vector_ready = self.text_vector_index.engine_name == "faiss"
        image_semantic_ready = (
            not self.image_embedder.degraded
            and self.image_embedder.engine_name == "openclip"
            and image_vector_ready
        )
        text_semantic_ready = (
            not self.text_embedder.degraded
            and text_vector_ready
        )
        text_search_ready = True
        image_scope_ready = image_semantic_ready
        document_scope_ready = text_semantic_ready
        voice_note_scope_ready = text_semantic_ready
        semantic_search_ready = image_semantic_ready or text_semantic_ready
        core_search_ready = image_scope_ready or document_scope_ready or voice_note_scope_ready

        if image_scope_ready and document_scope_ready and voice_note_scope_ready:
            core_search_phase = "ready"
            core_search_message = "Image, document, and voice-note search are fully ready."
        elif image_scope_ready:
            core_search_phase = "ready"
            core_search_message = (
                "Image search is ready. Document and voice-note semantic search will finish once "
                "the local text models are available."
            )
        elif document_scope_ready or voice_note_scope_ready:
            core_search_phase = "ready"
            core_search_message = (
                "Document and voice-note search are ready. Image semantic search will finish once "
                "the local vision model is available."
            )
        else:
            core_search_phase = "limited"
            core_search_message = (
                "Recall could not finish its preferred multi-asset semantic search startup. "
                "Some scope filters may stay limited until local models are available."
            )

        indexing_phase = "deferred"
        if ocr_status["phase"] == "warming" or transcription_status["phase"] == "warming":
            indexing_phase = "warming"
        elif ocr_status["phase"] == "ready" or transcription_status["phase"] == "ready":
            indexing_phase = "ready"
        elif ocr_status["phase"] == "limited" or transcription_status["phase"] == "limited":
            indexing_phase = "limited"

        indexing_message = (
            "OCR and transcription stay deferred until indexing needs them."
            if indexing_phase == "deferred"
            else "Indexing services are available on demand."
        )
        degraded = (
            not core_search_ready
            or bool(ocr_status["degraded"])
            or bool(transcription_status["degraded"])
        )
        return {
            "workerReady": True,
            "databaseReady": True,
            "textSearchReady": text_search_ready,
            "semanticSearchReady": semantic_search_ready,
            "imageSemanticReady": image_semantic_ready,
            "textSemanticReady": text_semantic_ready,
            "imageVectorReady": image_vector_ready,
            "textVectorReady": text_vector_ready,
            "imageScopeReady": image_scope_ready,
            "documentScopeReady": document_scope_ready,
            "voiceNoteScopeReady": voice_note_scope_ready,
            "coreSearchReady": core_search_ready,
            "coreSearchPhase": core_search_phase,
            "coreSearchMessage": core_search_message,
            "indexingPhase": indexing_phase,
            "indexingMessage": indexing_message,
            "vectorEngine": f"images:{self.image_vector_index.engine_name}, text:{self.text_vector_index.engine_name}",
            "ocrEngine": ocr_status["engine_name"],
            "embeddingEngine": f"images:{self.image_embedder.engine_name}, text:{self.text_embedder.engine_name}",
            "degraded": degraded,
            "message": (
                "Core multi-asset search is ready. OCR and transcription will load on demand."
                if core_search_ready
                else core_search_message
            ),
            "startupMetrics": {
                "coreSearchReadyMs": self._startup_metrics["coreSearchReadyMs"],
                "embeddingInitMs": self._startup_metrics["embeddingInitMs"],
                "vectorBootstrapMs": self._startup_metrics["vectorBootstrapMs"],
                "ocrInitMs": ocr_status["last_init_ms"] or transcription_status["last_init_ms"],
                "vectorBootstrapMode": self._startup_metrics["vectorBootstrapMode"],
            },
        }

    def _refresh_health_snapshot(self) -> None:
        with self._health_lock:
            self._cached_health = self._compute_health_snapshot()

    def _repair_missing_document_previews(self) -> None:
        try:
            while not self._shutdown_requested:
                rows = self.database.list_documents_missing_previews(limit=25)
                if not rows:
                    return
                for row in rows:
                    if self._shutdown_requested:
                        return
                    document_path = Path(row["path"])
                    if not document_path.exists():
                        continue
                    content_hash = row["content_hash"]
                    preview_path = self.config.thumbnail_dir / f"{content_hash}-document.jpg"
                    chunk_rows = self.database.fetch_asset_chunks(int(row["id"]))
                    chunks = [
                        TextChunk(
                            text=row["chunk_text"],
                            chunk_index=int(row["chunk_index"]),
                            chunk_type=row["chunk_type"],
                            page_number=row["page_number"],
                            start_ms=row["start_ms"],
                            end_ms=row["end_ms"],
                        )
                        for row in chunk_rows
                    ]
                    rendered_path = render_document_preview(
                        document_path,
                        preview_path,
                        max_size=self.config.max_thumbnail_size * 2,
                        chunks=chunks,
                    )
                    self.database.update_asset_preview(
                        int(row["id"]),
                        str(rendered_path),
                        utcnow_iso(),
                    )
        except Exception as error:  # noqa: BLE001
            print(
                f"Document preview backfill failed: {error}",
                file=sys.stderr,
                flush=True,
            )

    def shutdown(self, params: dict | None = None) -> dict:
        del params
        with self._scheduler_condition:
            self._shutdown_requested = True
            self._scheduler_condition.notify_all()
        return {"shuttingDown": True}

    def dispatch(self, method: str, params: dict) -> object:
        handlers = {
            "add_folders": self.add_folders,
            "list_folders": self.list_folders,
            "remove_folder": self.remove_folder,
            "process_fs_events": self.process_fs_events,
            "rebuild_index": self.rebuild_index,
            "search": self.search,
            "search_assets": self.search_assets,
            "get_status": self.get_status,
            "get_health": self.get_health,
            "shutdown": self.shutdown,
        }
        if method not in handlers:
            raise ValueError(f"Unknown worker method: {method}")
        return handlers[method](params)

    def _enqueue(self, job_type: str, payload: dict) -> None:
        with self._scheduler_condition:
            if job_type == "fs_events":
                self._merge_fs_events_locked(payload.get("events") or [])
            else:
                self._merge_full_index_locked(payload)
            self._scheduler_condition.notify()

    def _queued_jobs_count(self) -> int:
        with self._scheduler_condition:
            return len(self._full_index_jobs) + (1 if self._pending_fs_events else 0)

    def _merge_fs_events_locked(self, events: list[dict]) -> None:
        for event in events:
            canonical_path = self._canonical_event_path(event.get("path", ""))
            if not canonical_path:
                continue
            kind = "delete" if event.get("kind") == "delete" else "modify"
            existing = self._pending_fs_events.get(canonical_path)
            if existing is not None:
                self._scheduler_metrics["coalescedFsEvents"] += 1
                if existing["kind"] == "delete":
                    continue
                if kind == "delete":
                    self._pending_fs_events[canonical_path] = {"kind": "delete", "path": canonical_path}
                continue
            self._pending_fs_events[canonical_path] = {"kind": kind, "path": canonical_path}
            self._scheduler_metrics["mergedFsEvents"] += 1

    def _merge_full_index_locked(self, payload: dict) -> None:
        normalized_folder_ids = self._normalize_folder_ids(payload.get("folderIds") or [])
        if not normalized_folder_ids:
            self._scheduler_metrics["dedupedFullIndexJobs"] += 1
            return

        remaining_folder_ids = [
            folder_id
            for folder_id in normalized_folder_ids
            if folder_id not in self._active_full_index_folder_ids
        ]
        if not remaining_folder_ids:
            self._scheduler_metrics["dedupedFullIndexJobs"] += 1
            return

        if not self._full_index_jobs:
            queued_payload = dict(payload)
            queued_payload["folderIds"] = remaining_folder_ids
            self._full_index_jobs.append(queued_payload)
            return

        pending_payload = self._full_index_jobs[0]
        pending_folder_ids = set(self._normalize_folder_ids(pending_payload.get("folderIds") or []))
        new_folder_ids = [folder_id for folder_id in remaining_folder_ids if folder_id not in pending_folder_ids]
        if not new_folder_ids:
            self._scheduler_metrics["dedupedFullIndexJobs"] += 1
            return

        pending_payload["folderIds"] = sorted((*pending_folder_ids, *new_folder_ids))
        pending_payload["triggerSource"] = payload.get("triggerSource", pending_payload.get("triggerSource", "system"))
        self._scheduler_metrics["mergedFullIndexJobs"] += 1

    @staticmethod
    def _normalize_folder_ids(folder_ids: list[int] | list[str]) -> list[int]:
        normalized = sorted({int(folder_id) for folder_id in folder_ids})
        return normalized

    @staticmethod
    def _canonical_event_path(path: str) -> str:
        if not path:
            return ""
        candidate = Path(path).expanduser()
        try:
            normalized = candidate.resolve(strict=False)
        except OSError:
            normalized = candidate.absolute()
        return str(normalized)

    def _rebuild_image_vector_index_from_batches(self, embeddings_state: dict[str, int | str | None]) -> int:
        batch_size = 512
        batch_count = 0
        self.image_vector_index.begin_rebuild()
        try:
            for batch in self.database.iter_embedding_batches(batch_size):
                self.image_vector_index.add_batch(batch)
                batch_count += 1
            self.image_vector_index.finish_rebuild(embeddings_state)
            return batch_count
        except Exception:
            self.image_vector_index.abort_rebuild()
            raise

    def _rebuild_text_vector_index_from_batches(self, embeddings_state: dict[str, int | str | None]) -> int:
        batch_size = 512
        batch_count = 0
        self.text_vector_index.begin_rebuild()
        try:
            iterator = (
                self.database.iter_text_embedding_batches(batch_size)
                if hasattr(self.database, "iter_text_embedding_batches")
                else self.database.iter_embedding_batches(batch_size)
            )
            for batch in iterator:
                self.text_vector_index.add_batch(batch)
                batch_count += 1
            self.text_vector_index.finish_rebuild(embeddings_state)
            return batch_count
        except Exception:
            self.text_vector_index.abort_rebuild()
            raise

    def _job_loop(self) -> None:
        while True:
            with self._scheduler_condition:
                while not self._shutdown_requested and not self._full_index_jobs and not self._pending_fs_events:
                    self._scheduler_condition.wait()
                if self._shutdown_requested:
                    return
                if self._full_index_jobs:
                    job_type = "full_index"
                    payload = self._full_index_jobs.pop(0)
                    self._active_full_index_folder_ids = set(
                        self._normalize_folder_ids(payload.get("folderIds") or [])
                    )
                else:
                    job_type = "fs_events"
                    payload = {
                        "events": list(self._pending_fs_events.values()),
                        "triggerSource": "watcher",
                    }
                    self._pending_fs_events.clear()
                    self._scheduler_metrics["dispatchedFsEvents"] += len(payload["events"])

            job_id = self.database.create_job(job_type, None, payload.get("triggerSource", "system"), utcnow_iso())
            with self._status_lock:
                self.status.state = "indexing"
                self.status.active_job_id = job_id
                self.status.active_job_type = job_type
                self.status.items_total = 0
                self.status.items_processed = 0
                self.status.last_error = None
            self._refresh_health_snapshot()

            try:
                if job_type == "full_index":
                    folder_ids = payload.get("folderIds") or []
                    folders = {int(folder["id"]): folder for folder in self.database.get_active_folder_records()}
                    for folder_id in folder_ids:
                        folder_record = folders.get(int(folder_id))
                        if not folder_record:
                            continue

                        last_progress_flush = 0.0
                        last_progress_processed = 0

                        def progress(total: int, processed: int) -> None:
                            nonlocal last_progress_flush, last_progress_processed
                            with self._status_lock:
                                self.status.items_total = total
                                self.status.items_processed = processed
                            now = time.perf_counter()
                            if (
                                processed == total
                                or processed - last_progress_processed >= 25
                                or now - last_progress_flush >= 0.25
                            ):
                                self.database.update_job_progress(job_id, total, processed)
                                last_progress_flush = now
                                last_progress_processed = processed

                        self.pipeline.scan_folder(folder_record, progress)
                elif job_type == "fs_events":
                    folders = self.database.list_folders()
                    self.pipeline.process_events(payload.get("events") or [], folders)

                self.database.finish_job(job_id, utcnow_iso(), "completed")
                with self._status_lock:
                    self.status.state = "idle"
                    self.status.active_job_id = None
                    self.status.active_job_type = None
                    self.status.last_completed_at = utcnow_iso()
                self._refresh_health_snapshot()
            except Exception as error:  # noqa: BLE001
                self.database.finish_job(job_id, utcnow_iso(), "failed", str(error))
                with self._status_lock:
                    self.status.state = "error"
                    self.status.active_job_id = None
                    self.status.active_job_type = None
                    self.status.last_error = str(error)
                self._refresh_health_snapshot()
                print(f"Worker job failed: {error}", file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)
            finally:
                if job_type == "full_index":
                    with self._scheduler_condition:
                        self._active_full_index_folder_ids.clear()


def main() -> None:
    worker = RecallWorker()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        request_id = None
        try:
            envelope = json.loads(line)
            request_id = envelope["id"]
            method = envelope["method"]
            params = envelope.get("params") or {}
            result = worker.dispatch(method, params)
            response = {"id": request_id, "result": result, "error": None}
        except Exception as error:  # noqa: BLE001
            response = {"id": request_id or 0, "result": None, "error": str(error)}
            print(f"Worker request failed: {error}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

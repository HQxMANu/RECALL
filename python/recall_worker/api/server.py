from __future__ import annotations

import json
import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from recall_worker.core.config import load_config
from recall_worker.db.database import Database
from recall_worker.embeddings.engine import create_embedder
from recall_worker.indexing.pipeline import IndexingPipeline, utcnow_iso
from recall_worker.ocr.engine import create_ocr_engine
from recall_worker.search.service import SearchService
from recall_worker.search.vector_index import create_vector_index


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
        embedding_started = time.perf_counter()
        self.embedder = create_embedder()
        embedding_init_ms = round((time.perf_counter() - embedding_started) * 1000)
        vector_started = time.perf_counter()
        self.vector_index = create_vector_index(self.embedder.dimension, self.config.vector_index_path)
        if self.vector_index.engine_name == "faiss":
            embedding_ids = self.database.list_embedding_ids()
            bootstrapped = self.vector_index.bootstrap(ids=embedding_ids)
            if not bootstrapped:
                self.vector_index.bootstrap(embeddings=self.database.list_all_embeddings())
        else:
            self.vector_index.bootstrap(embeddings=self.database.list_all_embeddings())
        vector_bootstrap_ms = round((time.perf_counter() - vector_started) * 1000)
        self.pipeline = IndexingPipeline(
            self.config,
            self.database,
            self.ocr_engine,
            self.embedder,
            self.vector_index,
        )
        self.search_service = SearchService(
            self.database,
            self.embedder,
            self.vector_index,
            self.config.search_limit,
        )
        self.status = RuntimeStatus()
        self._status_lock = threading.RLock()
        self._job_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._job_thread = threading.Thread(target=self._job_loop, daemon=True, name="recall-indexer")
        self._job_thread.start()
        self._startup_metrics = {
            "databaseReadyMs": database_ready_ms,
            "embeddingInitMs": embedding_init_ms,
            "vectorBootstrapMs": vector_bootstrap_ms,
            "coreSearchReadyMs": round((time.perf_counter() - startup_started) * 1000),
            "vectorBootstrapMode": getattr(self.vector_index, "bootstrap_mode", "unknown"),
        }
        print(
            (
                "Core search ready in "
                f"{self._startup_metrics['coreSearchReadyMs']} ms "
                f"(embedder {embedding_init_ms} ms, vector {vector_bootstrap_ms} ms, "
                f"mode {self._startup_metrics['vectorBootstrapMode']})"
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
        removed_ids = self.database.delete_folder(folder_id)
        for image_id in removed_ids:
            self.vector_index.remove(image_id)
        return {"removedImageIds": removed_ids}

    def process_fs_events(self, params: dict) -> dict:
        self._enqueue("fs_events", {"events": params.get("events") or [], "triggerSource": "watcher"})
        return {"queued": True}

    def rebuild_index(self, params: dict) -> dict:
        folder_ids = params.get("folderIds") or [folder["id"] for folder in self.database.list_folders()]
        self._enqueue("full_index", {"folderIds": folder_ids, "triggerSource": "manual_rebuild"})
        return {"queued": True}

    def search(self, params: dict) -> dict:
        return self.search_service.search(params.get("request") or {})

    def get_status(self, params: dict | None = None) -> dict:
        del params
        with self._status_lock:
            return {
                "state": self.status.state,
                "activeJobId": self.status.active_job_id,
                "activeJobType": self.status.active_job_type,
                "itemsTotal": self.status.items_total,
                "itemsProcessed": self.status.items_processed,
                "queuedJobs": self._job_queue.qsize(),
                "lastCompletedAt": self.status.last_completed_at,
                "lastError": self.status.last_error,
            }

    def get_health(self, params: dict | None = None) -> dict:
        del params
        ocr_status = self.ocr_engine.status()
        semantic_search_ready = (
            not self.embedder.degraded
            and self.embedder.engine_name == "openclip"
            and self.vector_index.engine_name == "faiss"
        )
        text_search_ready = True
        core_search_ready = text_search_ready and semantic_search_ready

        if core_search_ready:
            core_search_phase = "ready"
            core_search_message = "Semantic and text search are fully ready."
        else:
            core_search_phase = "limited"
            core_search_message = (
                "Recall could not finish its preferred semantic search startup. "
                "Description-based search stays disabled until OpenCLIP and FAISS are available."
            )

        indexing_phase = str(ocr_status["phase"])
        if indexing_phase == "deferred":
            indexing_message = "OCR stays deferred until indexing starts."
        elif indexing_phase == "warming":
            indexing_message = "Recall is loading OCR for an indexing job."
        elif indexing_phase == "ready":
            indexing_message = f"OCR is ready with {ocr_status['engine_name']}."
        else:
            indexing_message = (
                f"OCR is limited: {ocr_status['last_error'] or 'No OCR engine was available.'}"
            )

        degraded = (
            not core_search_ready
            or bool(ocr_status["degraded"])
            or self.ocr_engine.engine_name not in {"deferred", "paddleocr"}
        )
        message = (
            "Core search is ready. OCR will load on demand for indexing."
            if core_search_ready
            else core_search_message
        )
        return {
            "workerReady": True,
            "databaseReady": True,
            "textSearchReady": text_search_ready,
            "semanticSearchReady": semantic_search_ready,
            "coreSearchReady": core_search_ready,
            "coreSearchPhase": core_search_phase,
            "coreSearchMessage": core_search_message,
            "indexingPhase": indexing_phase,
            "indexingMessage": indexing_message,
            "vectorEngine": self.vector_index.engine_name,
            "ocrEngine": self.ocr_engine.engine_name,
            "embeddingEngine": self.embedder.engine_name,
            "degraded": degraded,
            "message": message,
            "startupMetrics": {
                "coreSearchReadyMs": self._startup_metrics["coreSearchReadyMs"],
                "embeddingInitMs": self._startup_metrics["embeddingInitMs"],
                "vectorBootstrapMs": self._startup_metrics["vectorBootstrapMs"],
                "ocrInitMs": ocr_status["last_init_ms"],
                "vectorBootstrapMode": self._startup_metrics["vectorBootstrapMode"],
            },
        }

    def shutdown(self, params: dict | None = None) -> dict:
        del params
        self._enqueue("shutdown", {})
        return {"shuttingDown": True}

    def dispatch(self, method: str, params: dict) -> object:
        handlers = {
            "add_folders": self.add_folders,
            "list_folders": self.list_folders,
            "remove_folder": self.remove_folder,
            "process_fs_events": self.process_fs_events,
            "rebuild_index": self.rebuild_index,
            "search": self.search,
            "get_status": self.get_status,
            "get_health": self.get_health,
            "shutdown": self.shutdown,
        }
        if method not in handlers:
            raise ValueError(f"Unknown worker method: {method}")
        return handlers[method](params)

    def _enqueue(self, job_type: str, payload: dict) -> None:
        self._job_queue.put((job_type, payload))

    def _job_loop(self) -> None:
        while True:
            job_type, payload = self._job_queue.get()
            if job_type == "shutdown":
                return

            job_id = self.database.create_job(job_type, None, payload.get("triggerSource", "system"), utcnow_iso())
            with self._status_lock:
                self.status.state = "indexing"
                self.status.active_job_id = job_id
                self.status.active_job_type = job_type
                self.status.items_total = 0
                self.status.items_processed = 0
                self.status.last_error = None

            try:
                if job_type == "full_index":
                    folder_ids = payload.get("folderIds") or []
                    folders = {
                        int(folder["id"]): folder for folder in self.database.get_active_folder_records()
                    }
                    for folder_id in folder_ids:
                        folder_record = folders.get(int(folder_id))
                        if not folder_record:
                            continue

                        def progress(total: int, processed: int) -> None:
                            with self._status_lock:
                                self.status.items_total = total
                                self.status.items_processed = processed
                            self.database.update_job_progress(job_id, total, processed)

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
            except Exception as error:  # noqa: BLE001
                self.database.finish_job(job_id, utcnow_iso(), "failed", str(error))
                with self._status_lock:
                    self.status.state = "error"
                    self.status.active_job_id = None
                    self.status.active_job_type = None
                    self.status.last_error = str(error)
                print(f"Worker job failed: {error}", file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)


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

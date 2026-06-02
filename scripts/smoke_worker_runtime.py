from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


SAMPLE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlAb7sAAAAASUVORK5CYII="
)


class WorkerHarness:
    def __init__(self, runtime_root: Path, app_data_dir: Path) -> None:
        self.runtime_root = runtime_root
        self.app_data_dir = app_data_dir
        self.response_queue: queue.Queue[dict] = queue.Queue()
        self._request_id = 0
        python_exe = runtime_root / ".venv" / "Scripts" / "python.exe"
        worker_script = runtime_root / "run_worker.py"

        if not python_exe.exists():
            raise FileNotFoundError(f"Staged python executable not found: {python_exe}")
        if not worker_script.exists():
            raise FileNotFoundError(f"Staged worker script not found: {worker_script}")

        offline_cache_root = app_data_dir / "offline-model-caches"
        offline_cache_root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUTF8": "1",
                "RECALL_APP_DATA_DIR": str(app_data_dir),
                "RECALL_MODEL_ROOT": str(runtime_root / "models"),
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
                "HF_HOME": str(offline_cache_root / "hf-home"),
                "HUGGINGFACE_HUB_CACHE": str(offline_cache_root / "hf-hub"),
                "TRANSFORMERS_CACHE": str(offline_cache_root / "transformers"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "USE_TF": "0",
                "TRANSFORMERS_NO_TF": "1",
            }
        )

        self.process = subprocess.Popen(
            [str(python_exe), str(worker_script)],
            cwd=runtime_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )

        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None

        self._stdout_thread = threading.Thread(
            target=self._read_stdout, args=(self.process.stdout,), daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._forward_stderr, args=(self.process.stderr,), daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self, stream) -> None:
        for raw_line in iter(stream.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            try:
                self.response_queue.put(json.loads(line))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"Worker returned invalid JSON: {line}") from error

    @staticmethod
    def _forward_stderr(stream) -> None:
        for raw_line in iter(stream.readline, ""):
            line = raw_line.rstrip()
            if line:
                sys.stderr.write(f"[worker] {line}\n")
                sys.stderr.flush()

    def request(self, method: str, params: dict, timeout_seconds: float) -> dict:
        self._request_id += 1
        request_id = self._request_id
        payload = {"id": request_id, "method": method, "params": params}
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Worker exited unexpectedly with code {self.process.returncode}")

            try:
                response = self.response_queue.get(timeout=min(1.0, deadline - time.time()))
            except queue.Empty:
                continue

            if response.get("id") != request_id:
                raise RuntimeError(
                    f"Mismatched worker response id {response.get('id')} for request {request_id}"
                )

            if response.get("error"):
                raise RuntimeError(f"Worker method {method} failed: {response['error']}")

            result = response.get("result")
            if result is None:
                raise RuntimeError(f"Worker method {method} returned no result")
            return result

        raise TimeoutError(f"Timed out waiting for worker method {method}")

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {}, timeout_seconds=5)
        except Exception:
            pass
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()


def create_sample_assets(sample_root: Path) -> None:
    sample_root.mkdir(parents=True, exist_ok=True)
    (sample_root / "release-smoke.txt").write_text(
        "Recall beta smoke test document. Search phrase: recall publish beta validation.\n",
        encoding="utf-8",
    )
    (sample_root / "release-smoke.png").write_bytes(base64.b64decode(SAMPLE_PNG_BASE64))


def wait_for_core_search_ready(worker: WorkerHarness, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        remaining = max(30.0, min(180.0, deadline - time.time()))
        health = worker.request("get_health", {}, timeout_seconds=remaining)
        if health.get("coreSearchReady"):
            return
        time.sleep(2)
    raise TimeoutError("Worker did not report core search ready before the timeout")


def wait_for_indexed_results(
    worker: WorkerHarness,
    folder_id: int,
    timeout_seconds: float,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = worker.request("get_status", {}, timeout_seconds=15)
        if status.get("state") == "error":
            raise RuntimeError(status.get("lastError") or "Indexing entered an error state")

        docs = worker.request(
            "search_assets",
            {
                "request": {
                    "query": "recall publish beta validation",
                    "scope": "documents",
                    "folderIds": [folder_id],
                    "sort": "relevance",
                    "limit": 10,
                    "offset": 0,
                }
            },
            timeout_seconds=20,
        )
        images = worker.request(
            "search_assets",
            {
                "request": {
                    "query": "",
                    "scope": "images",
                    "folderIds": [folder_id],
                    "sort": "newest",
                    "limit": 10,
                    "offset": 0,
                }
            },
            timeout_seconds=20,
        )
        if docs.get("totalHits", 0) >= 1 and images.get("totalHits", 0) >= 1:
            return

        time.sleep(2)

    raise TimeoutError("Sample assets were not indexed and searchable before the timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the staged Recall worker runtime.")
    parser.add_argument("--runtime-root", required=True, help="Path to src-tauri/resources/python")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=420,
        help="Overall timeout budget for the smoke run.",
    )
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    if not runtime_root.exists():
        raise FileNotFoundError(f"Runtime root not found: {runtime_root}")

    temp_root = Path(tempfile.mkdtemp(prefix="recall-worker-smoke-"))
    app_data_dir = temp_root / "app-data"
    sample_root = temp_root / "sample-assets"
    create_sample_assets(sample_root)

    worker = WorkerHarness(runtime_root, app_data_dir)
    try:
        wait_for_core_search_ready(worker, timeout_seconds=args.timeout_seconds)
        add_result = worker.request(
            "add_folders",
            {"paths": [str(sample_root)]},
            timeout_seconds=20,
        )
        added_folders = add_result.get("addedFolders") or []
        if not added_folders:
            raise RuntimeError("Smoke test folder was not accepted by add_folders")
        folder_id = int(added_folders[0]["id"])
        wait_for_indexed_results(worker, folder_id, timeout_seconds=args.timeout_seconds)
        print(
            f"Recall worker smoke test passed for {runtime_root} using sample folder {sample_root}",
            flush=True,
        )
        return 0
    finally:
        worker.shutdown()
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"Recall worker smoke test failed: {error}", file=sys.stderr, flush=True)
        raise

import threading
import unittest
from pathlib import Path

from recall_worker.api.server import RecallWorker


class WorkerSchedulerTests(unittest.TestCase):
    def test_merge_fs_events_coalesces_duplicate_paths(self) -> None:
        worker = RecallWorker.__new__(RecallWorker)
        worker._pending_fs_events = {}
        worker._scheduler_metrics = {
            "mergedFsEvents": 0,
            "coalescedFsEvents": 0,
            "dispatchedFsEvents": 0,
        }
        worker._scheduler_condition = threading.Condition()

        raw_path = "C:/Images/photo.png"
        expected_path = str(Path(raw_path).expanduser().resolve(strict=False))

        worker._merge_fs_events_locked(
            [
                {"path": raw_path, "kind": "modify"},
                {"path": raw_path, "kind": "modify"},
                {"path": raw_path, "kind": "delete"},
            ]
        )

        self.assertEqual(
            worker._pending_fs_events,
            {expected_path: {"kind": "delete", "path": expected_path}},
        )
        self.assertEqual(worker._scheduler_metrics["mergedFsEvents"], 1)
        self.assertEqual(worker._scheduler_metrics["coalescedFsEvents"], 2)


if __name__ == "__main__":
    unittest.main()

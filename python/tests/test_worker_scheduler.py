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

    def test_full_index_requests_are_deduped_and_merged(self) -> None:
        worker = RecallWorker.__new__(RecallWorker)
        worker._scheduler_condition = threading.Condition()
        worker._full_index_jobs = []
        worker._pending_fs_events = {}
        worker._active_full_index_folder_ids = {1, 2}
        worker._scheduler_metrics = {
            "mergedFsEvents": 0,
            "coalescedFsEvents": 0,
            "dispatchedFsEvents": 0,
            "mergedFullIndexJobs": 0,
            "dedupedFullIndexJobs": 0,
        }

        worker._enqueue("full_index", {"folderIds": [1, 2], "triggerSource": "manual_rebuild"})
        self.assertEqual(worker._full_index_jobs, [])
        self.assertEqual(worker._scheduler_metrics["dedupedFullIndexJobs"], 1)

        worker._enqueue("full_index", {"folderIds": [2, 3], "triggerSource": "manual_rebuild"})
        self.assertEqual(len(worker._full_index_jobs), 1)
        self.assertEqual(worker._full_index_jobs[0]["folderIds"], [3])

        worker._enqueue("full_index", {"folderIds": [3, 4], "triggerSource": "user"})
        self.assertEqual(len(worker._full_index_jobs), 1)
        self.assertEqual(worker._full_index_jobs[0]["folderIds"], [3, 4])
        self.assertEqual(worker._full_index_jobs[0]["triggerSource"], "user")
        self.assertEqual(worker._scheduler_metrics["mergedFullIndexJobs"], 1)


if __name__ == "__main__":
    unittest.main()

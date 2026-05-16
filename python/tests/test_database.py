import tempfile
import unittest
from pathlib import Path

from recall_worker.db.database import Database


class DatabaseTests(unittest.TestCase):
    def test_folder_insert_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "recall.db")
            added, skipped = database.add_or_reactivate_folders(
                ["C:\\Images\\Screenshots"],
                "2026-05-14T00:00:00+00:00",
            )

            self.assertEqual(skipped, [])
            self.assertEqual(len(added), 1)
            self.assertEqual(database.list_folders()[0]["displayName"], "Screenshots")
            database.close()


if __name__ == "__main__":
    unittest.main()

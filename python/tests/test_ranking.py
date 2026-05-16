import unittest

from recall_worker.search.ranking import blend_results


class RankingTests(unittest.TestCase):
    def test_blend_results_prefers_items_present_in_both_sets(self) -> None:
        metadata = {
            1: {
                "path": "one.png",
                "filename": "one.png",
                "modified_at_fs": "2026-05-14T12:00:00+00:00",
                "folder_id": 1,
                "folder_name": "Screenshots",
                "thumbnail_path": None,
                "created_at_fs": None,
                "ocr_text": "wifi password",
                "width": 1,
                "height": 1,
            },
            2: {
                "path": "two.png",
                "filename": "two.png",
                "modified_at_fs": "2025-05-14T12:00:00+00:00",
                "folder_id": 1,
                "folder_name": "Screenshots",
                "thumbnail_path": None,
                "created_at_fs": None,
                "ocr_text": "router settings",
                "width": 1,
                "height": 1,
            },
        }

        results, _ = blend_results(
            query="wifi password screenshot",
            text_ranked_ids=[1],
            semantic_ranked_ids=[1, 2],
            metadata_by_id=metadata,
            sort="relevance",
        )

        self.assertEqual(results[0]["imageId"], 1)


if __name__ == "__main__":
    unittest.main()

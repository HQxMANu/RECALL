import unittest
from unittest.mock import Mock

import numpy as np

from recall_worker.search.service import SearchService


class SearchServiceTests(unittest.TestCase):
    def test_filtered_semantic_search_fetches_metadata_once(self) -> None:
        database = Mock()
        database.fts_search.return_value = []
        database.fetch_images_by_ids.return_value = {
            1: {
                "id": 1,
                "path": "one.png",
                "filename": "one.png",
                "modified_at_fs": "2026-05-14T12:00:00+00:00",
                "created_at_fs": None,
                "ocr_text": "match",
                "folder_id": 1,
                "folder_name": "Photos",
                "thumbnail_path": None,
                "width": 10,
                "height": 10,
            },
            2: {
                "id": 2,
                "path": "two.png",
                "filename": "two.png",
                "modified_at_fs": "2026-05-14T12:00:00+00:00",
                "created_at_fs": None,
                "ocr_text": "skip",
                "folder_id": 2,
                "folder_name": "Archive",
                "thumbnail_path": None,
                "width": 10,
                "height": 10,
            },
        }
        embedder = Mock()
        embedder.embed_text.return_value = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vector_index = Mock()
        vector_index.search.return_value = [(1, 0.9), (2, 0.8)]

        service = SearchService(database, embedder, vector_index, 200)

        response = service.search(
            {
                "query": "match",
                "folderIds": [1],
                "sort": "relevance",
                "limit": 50,
                "offset": 0,
            }
        )

        self.assertEqual(database.fetch_images_by_ids.call_count, 1)
        self.assertEqual([result["imageId"] for result in response["results"]], [1])


if __name__ == "__main__":
    unittest.main()

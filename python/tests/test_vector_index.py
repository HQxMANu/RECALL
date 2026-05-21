import unittest

import numpy as np

from recall_worker.search.vector_index import NumpyVectorIndex


class NumpyVectorIndexTests(unittest.TestCase):
    def test_rebuild_reuses_live_storage_in_numpy_fallback(self) -> None:
        index = NumpyVectorIndex(4)
        index.upsert(1, np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
        original_storage = index._vectors  # noqa: SLF001

        index.begin_rebuild()
        index.add_batch(
            [
                (2, np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)),
                (3, np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)),
            ]
        )
        index.finish_rebuild()

        self.assertIs(index._vectors, original_storage)  # noqa: SLF001
        self.assertEqual(index._count, 2)  # noqa: SLF001
        self.assertNotIn(1, index._vectors)  # noqa: SLF001
        self.assertEqual(set(index._vectors), {2, 3})  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()

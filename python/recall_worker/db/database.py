from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS indexed_folders (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_images (
  id INTEGER PRIMARY KEY,
  folder_id INTEGER NOT NULL REFERENCES indexed_folders(id) ON DELETE CASCADE,
  path TEXT NOT NULL UNIQUE,
  filename TEXT NOT NULL,
  extension TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at_fs TEXT,
  modified_at_fs TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  width INTEGER,
  height INTEGER,
  ocr_text TEXT,
  thumbnail_path TEXT,
  last_indexed_at TEXT NOT NULL,
  index_status TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
  image_id INTEGER PRIMARY KEY REFERENCES indexed_images(id) ON DELETE CASCADE,
  model_name TEXT NOT NULL,
  vector_dim INTEGER NOT NULL,
  vector_blob BLOB NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexing_jobs (
  id INTEGER PRIMARY KEY,
  job_type TEXT NOT NULL,
  folder_id INTEGER,
  status TEXT NOT NULL,
  items_total INTEGER NOT NULL DEFAULT 0,
  items_processed INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  trigger_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_folder_id ON indexed_images(folder_id);
CREATE INDEX IF NOT EXISTS idx_images_modified ON indexed_images(modified_at_fs);
CREATE INDEX IF NOT EXISTS idx_images_hash ON indexed_images(content_hash);
CREATE INDEX IF NOT EXISTS idx_images_status ON indexed_images(index_status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON indexing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_started_at ON indexing_jobs(started_at);

CREATE VIRTUAL TABLE IF NOT EXISTS indexed_images_fts USING fts5(
  filename,
  ocr_text,
  path,
  content='indexed_images',
  content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS indexed_images_ai AFTER INSERT ON indexed_images BEGIN
  INSERT INTO indexed_images_fts(rowid, filename, ocr_text, path)
  VALUES (new.id, new.filename, COALESCE(new.ocr_text, ''), new.path);
END;

CREATE TRIGGER IF NOT EXISTS indexed_images_ad AFTER DELETE ON indexed_images BEGIN
  INSERT INTO indexed_images_fts(indexed_images_fts, rowid, filename, ocr_text, path)
  VALUES('delete', old.id, old.filename, COALESCE(old.ocr_text, ''), old.path);
END;

CREATE TRIGGER IF NOT EXISTS indexed_images_au AFTER UPDATE ON indexed_images BEGIN
  INSERT INTO indexed_images_fts(indexed_images_fts, rowid, filename, ocr_text, path)
  VALUES('delete', old.id, old.filename, COALESCE(old.ocr_text, ''), old.path);
  INSERT INTO indexed_images_fts(rowid, filename, ocr_text, path)
  VALUES (new.id, new.filename, COALESCE(new.ocr_text, ''), new.path);
END;
"""


class Database:
    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock:
            self._connection.executescript(SCHEMA_SQL)
            self._ensure_embeddings_revision_locked()
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def add_or_reactivate_folders(
        self,
        canonical_paths: Sequence[str],
        created_at: str,
    ) -> tuple[list[dict], list[str]]:
        added: list[dict] = []
        skipped: list[str] = []
        with self._lock:
            for path in canonical_paths:
                existing = self._connection.execute(
                    "SELECT id FROM indexed_folders WHERE path = ?",
                    (path,),
                ).fetchone()
                if existing:
                    self._connection.execute(
                        """
                        UPDATE indexed_folders
                        SET is_active = 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (created_at, existing["id"]),
                    )
                else:
                    self._connection.execute(
                        """
                        INSERT INTO indexed_folders(path, display_name, is_active, created_at, updated_at)
                        VALUES (?, ?, 1, ?, ?)
                        """,
                        (path, Path(path).name or path, created_at, created_at),
                    )

                folder = self._connection.execute(
                    """
                    SELECT f.id, f.path, f.display_name, f.is_active,
                           COUNT(i.id) AS image_count,
                           MAX(i.last_indexed_at) AS last_indexed_at
                    FROM indexed_folders f
                    LEFT JOIN indexed_images i ON i.folder_id = f.id
                    WHERE f.path = ?
                    GROUP BY f.id
                    """,
                    (path,),
                ).fetchone()
                if folder:
                    added.append(self._folder_row(folder))
                else:
                    skipped.append(path)

            self._connection.commit()
        return added, skipped

    def list_folders(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT f.id, f.path, f.display_name, f.is_active,
                       COUNT(i.id) AS image_count,
                       MAX(i.last_indexed_at) AS last_indexed_at
                FROM indexed_folders f
                LEFT JOIN indexed_images i ON i.folder_id = f.id
                WHERE f.is_active = 1
                GROUP BY f.id
                ORDER BY f.display_name COLLATE NOCASE
                """
            ).fetchall()
        return [self._folder_row(row) for row in rows]

    def get_active_folder_records(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_folders WHERE is_active = 1 ORDER BY display_name COLLATE NOCASE"
            ).fetchall()

    def get_folder(self, folder_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_folders WHERE id = ?",
                (folder_id,),
            ).fetchone()

    def delete_folder(self, folder_id: int) -> list[int]:
        with self._lock:
            image_ids = [
                row["id"]
                for row in self._connection.execute(
                    "SELECT id FROM indexed_images WHERE folder_id = ?",
                    (folder_id,),
                ).fetchall()
            ]
            self._connection.execute("DELETE FROM indexed_folders WHERE id = ?", (folder_id,))
            if image_ids:
                self._increment_embeddings_revision_locked()
            self._connection.commit()
        return image_ids

    def get_image_by_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_images WHERE path = ?",
                (path,),
            ).fetchone()

    def get_image_by_hash(self, content_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_images WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()

    def get_embedding_vector(self, image_id: int) -> np.ndarray | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT vector_blob FROM embeddings WHERE image_id = ?",
                (image_id,),
            ).fetchone()
        if not row:
            return None
        return np.frombuffer(row["vector_blob"], dtype=np.float32)

    def upsert_image(self, payload: dict) -> int:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO indexed_images(
                  folder_id, path, filename, extension, content_hash, created_at_fs, modified_at_fs,
                  file_size_bytes, width, height, ocr_text, thumbnail_path,
                  last_indexed_at, index_status, error_code, error_message
                )
                VALUES (
                  :folder_id, :path, :filename, :extension, :content_hash, :created_at_fs, :modified_at_fs,
                  :file_size_bytes, :width, :height, :ocr_text, :thumbnail_path,
                  :last_indexed_at, :index_status, :error_code, :error_message
                )
                ON CONFLICT(path) DO UPDATE SET
                  folder_id = excluded.folder_id,
                  filename = excluded.filename,
                  extension = excluded.extension,
                  content_hash = excluded.content_hash,
                  created_at_fs = excluded.created_at_fs,
                  modified_at_fs = excluded.modified_at_fs,
                  file_size_bytes = excluded.file_size_bytes,
                  width = excluded.width,
                  height = excluded.height,
                  ocr_text = excluded.ocr_text,
                  thumbnail_path = excluded.thumbnail_path,
                  last_indexed_at = excluded.last_indexed_at,
                  index_status = excluded.index_status,
                  error_code = excluded.error_code,
                  error_message = excluded.error_message
                """,
                payload,
            )
            image_id = self._connection.execute(
                "SELECT id FROM indexed_images WHERE path = ?",
                (payload["path"],),
            ).fetchone()["id"]
            self._connection.commit()
        return int(image_id)

    def upsert_embedding(self, image_id: int, model_name: str, vector: np.ndarray, timestamp: str) -> None:
        self.upsert_embeddings_batch(
            [(image_id, model_name, vector, timestamp)],
            bump_revision=True,
        )

    def upsert_embeddings_batch(
        self,
        records: Sequence[tuple[int, str, np.ndarray, str]],
        *,
        bump_revision: bool = True,
    ) -> int:
        if not records:
            return self.get_embeddings_revision()
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO embeddings(image_id, model_name, vector_dim, vector_blob, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(image_id) DO UPDATE SET
                  model_name = excluded.model_name,
                  vector_dim = excluded.vector_dim,
                  vector_blob = excluded.vector_blob,
                  updated_at = excluded.updated_at
                """,
                [
                    (
                        image_id,
                        model_name,
                        int(vector.shape[0]),
                        vector.astype(np.float32).tobytes(),
                        timestamp,
                    )
                    for image_id, model_name, vector, timestamp in records
                ],
            )
            revision = self._increment_embeddings_revision_locked() if bump_revision else self._read_embeddings_revision_locked()
            self._connection.commit()
        return revision

    def list_all_embeddings(self) -> list[tuple[int, np.ndarray]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT image_id, vector_blob FROM embeddings"
            ).fetchall()
        return [
            (int(row["image_id"]), np.frombuffer(row["vector_blob"], dtype=np.float32))
            for row in rows
        ]

    def iter_embedding_batches(
        self,
        batch_size: int,
    ) -> Iterator[list[tuple[int, np.ndarray]]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT image_id, vector_blob
                FROM embeddings
                ORDER BY image_id ASC
                """
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield [
                    (int(row["image_id"]), np.frombuffer(row["vector_blob"], dtype=np.float32))
                    for row in rows
                ]

    def list_embedding_ids(self) -> list[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT image_id FROM embeddings ORDER BY image_id"
            ).fetchall()
        return [int(row["image_id"]) for row in rows]

    def get_embeddings_state(self) -> dict[str, int | str | None]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS count,
                       MIN(model_name) AS model_name,
                       MAX(vector_dim) AS vector_dim
                FROM embeddings
                """
            ).fetchone()
            revision = self._read_embeddings_revision_locked()
        return {
            "revision": revision,
            "count": int(row["count"] or 0),
            "model_name": row["model_name"],
            "vector_dim": int(row["vector_dim"]) if row["vector_dim"] is not None else None,
        }

    def get_embeddings_revision(self) -> int:
        with self._lock:
            return self._read_embeddings_revision_locked()

    def delete_image(self, path: str) -> int | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id FROM indexed_images WHERE path = ?",
                (path,),
            ).fetchone()
            if not row:
                return None
            self._connection.execute("DELETE FROM indexed_images WHERE path = ?", (path,))
            self._increment_embeddings_revision_locked()
            self._connection.commit()
        return int(row["id"])

    def prune_folder_images(self, folder_id: int, seen_paths: set[str]) -> list[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, path FROM indexed_images WHERE folder_id = ?",
                (folder_id,),
            ).fetchall()
            stale_ids = [int(row["id"]) for row in rows if row["path"] not in seen_paths]
            if stale_ids:
                placeholders = ",".join("?" for _ in stale_ids)
                self._connection.execute(
                    f"DELETE FROM indexed_images WHERE id IN ({placeholders})",
                    stale_ids,
                )
                self._increment_embeddings_revision_locked()
                self._connection.commit()
        return stale_ids

    def upsert_images_batch(self, payloads: Sequence[dict]) -> dict[str, int]:
        if not payloads:
            return {}
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO indexed_images(
                  folder_id, path, filename, extension, content_hash, created_at_fs, modified_at_fs,
                  file_size_bytes, width, height, ocr_text, thumbnail_path,
                  last_indexed_at, index_status, error_code, error_message
                )
                VALUES (
                  :folder_id, :path, :filename, :extension, :content_hash, :created_at_fs, :modified_at_fs,
                  :file_size_bytes, :width, :height, :ocr_text, :thumbnail_path,
                  :last_indexed_at, :index_status, :error_code, :error_message
                )
                ON CONFLICT(path) DO UPDATE SET
                  folder_id = excluded.folder_id,
                  filename = excluded.filename,
                  extension = excluded.extension,
                  content_hash = excluded.content_hash,
                  created_at_fs = excluded.created_at_fs,
                  modified_at_fs = excluded.modified_at_fs,
                  file_size_bytes = excluded.file_size_bytes,
                  width = excluded.width,
                  height = excluded.height,
                  ocr_text = excluded.ocr_text,
                  thumbnail_path = excluded.thumbnail_path,
                  last_indexed_at = excluded.last_indexed_at,
                  index_status = excluded.index_status,
                  error_code = excluded.error_code,
                  error_message = excluded.error_message
                """,
                payloads,
            )
            placeholders = ",".join("?" for _ in payloads)
            rows = self._connection.execute(
                f"SELECT id, path FROM indexed_images WHERE path IN ({placeholders})",
                [payload["path"] for payload in payloads],
            ).fetchall()
            self._connection.commit()
        return {row["path"]: int(row["id"]) for row in rows}

    def create_job(self, job_type: str, folder_id: int | None, trigger_source: str, started_at: str) -> int:
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO indexing_jobs(job_type, folder_id, status, items_total, items_processed, started_at, trigger_source)
                VALUES (?, ?, 'running', 0, 0, ?, ?)
                """,
                (job_type, folder_id, started_at, trigger_source),
            )
            self._connection.commit()
        return int(cursor.lastrowid)

    def recover_running_jobs(self, finished_at: str, error_message: str) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE indexing_jobs
                SET status = 'failed', finished_at = ?, error_message = COALESCE(error_message, ?)
                WHERE status = 'running' AND finished_at IS NULL
                """,
                (finished_at, error_message),
            )
            self._connection.commit()

    def update_job_progress(self, job_id: int, items_total: int, items_processed: int) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE indexing_jobs
                SET items_total = ?, items_processed = ?
                WHERE id = ?
                """,
                (items_total, items_processed, job_id),
            )
            self._connection.commit()

    def finish_job(self, job_id: int, finished_at: str, status: str, error_message: str | None = None) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE indexing_jobs
                SET status = ?, finished_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, finished_at, error_message, job_id),
            )
            self._connection.commit()

    def fts_search(self, query: str, folder_ids: Sequence[int] | None, limit: int) -> list[sqlite3.Row]:
        sql = """
        SELECT i.*, f.display_name AS folder_name, bm25(indexed_images_fts) AS text_rank
        FROM indexed_images_fts
        JOIN indexed_images i ON i.id = indexed_images_fts.rowid
        JOIN indexed_folders f ON f.id = i.folder_id
        WHERE indexed_images_fts MATCH ?
        """
        params: list[object] = [query]
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            sql += f" AND i.folder_id IN ({placeholders})"
            params.extend(folder_ids)
        sql += " ORDER BY text_rank LIMIT ?"
        params.append(limit)
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    def recent_images(
        self,
        folder_ids: Sequence[int] | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[sqlite3.Row]:
        order = "DESC" if sort != "oldest" else "ASC"
        sql = """
        SELECT i.*, f.display_name AS folder_name
        FROM indexed_images i
        JOIN indexed_folders f ON f.id = i.folder_id
        WHERE 1 = 1
        """
        params: list[object] = []
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            sql += f" AND i.folder_id IN ({placeholders})"
            params.extend(folder_ids)
        sql += f" ORDER BY i.modified_at_fs {order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._lock:
            return self._connection.execute(sql, params).fetchall()

    def fetch_images_by_ids(self, image_ids: Iterable[int]) -> dict[int, sqlite3.Row]:
        ids = list(dict.fromkeys(int(image_id) for image_id in image_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT i.*, f.display_name AS folder_name
                FROM indexed_images i
                JOIN indexed_folders f ON f.id = i.folder_id
                WHERE i.id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        return {int(row["id"]): row for row in rows}

    def _ensure_embeddings_revision_locked(self) -> None:
        self._connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES ('embeddings_revision', '0', 'system')
            ON CONFLICT(key) DO NOTHING
            """
        )

    def _read_embeddings_revision_locked(self) -> int:
        self._ensure_embeddings_revision_locked()
        row = self._connection.execute(
            "SELECT value_json FROM app_settings WHERE key = 'embeddings_revision'"
        ).fetchone()
        if not row or row["value_json"] is None:
            return 0
        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            try:
                return int(row["value_json"])
            except (TypeError, ValueError):
                return 0
        return int(value)

    def _increment_embeddings_revision_locked(self) -> int:
        revision = self._read_embeddings_revision_locked() + 1
        self._connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES ('embeddings_revision', ?, 'system')
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (json.dumps(revision),),
        )
        return revision

    @staticmethod
    def _folder_row(row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "path": row["path"],
            "displayName": row["display_name"],
            "isActive": bool(row["is_active"]),
            "imageCount": int(row["image_count"] or 0),
            "lastIndexedAt": row["last_indexed_at"],
        }

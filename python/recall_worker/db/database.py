from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np


IMAGE_ASSET_BACKFILL_VERSION = 1
IMAGE_ASSET_BACKFILL_KEY = "image_assets_backfill_version"


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

CREATE TABLE IF NOT EXISTS indexed_assets (
  id INTEGER PRIMARY KEY,
  folder_id INTEGER NOT NULL REFERENCES indexed_folders(id) ON DELETE CASCADE,
  asset_type TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  filename TEXT NOT NULL,
  extension TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at_fs TEXT,
  modified_at_fs TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  width INTEGER,
  height INTEGER,
  duration_ms INTEGER,
  preview_path TEXT,
  last_indexed_at TEXT NOT NULL,
  index_status TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS asset_chunks (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL REFERENCES indexed_assets(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_type TEXT NOT NULL,
  chunk_text TEXT NOT NULL,
  page_number INTEGER,
  start_ms INTEGER,
  end_ms INTEGER
);

CREATE TABLE IF NOT EXISTS text_embeddings (
  chunk_id INTEGER PRIMARY KEY REFERENCES asset_chunks(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_assets_folder_id ON indexed_assets(folder_id);
CREATE INDEX IF NOT EXISTS idx_assets_type ON indexed_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_modified ON indexed_assets(modified_at_fs);
CREATE INDEX IF NOT EXISTS idx_assets_hash ON indexed_assets(content_hash);
CREATE INDEX IF NOT EXISTS idx_assets_status ON indexed_assets(index_status);
CREATE INDEX IF NOT EXISTS idx_chunks_asset_id ON asset_chunks(asset_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON asset_chunks(chunk_type);
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

CREATE VIRTUAL TABLE IF NOT EXISTS asset_chunks_fts USING fts5(
  filename,
  chunk_text,
  path,
  asset_id UNINDEXED
);
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
            self._ensure_revision_locked("embeddings_revision")
            self._ensure_revision_locked("text_embeddings_revision")
            self._ensure_image_asset_backfill_locked()
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
                    self._folder_aggregate_sql("WHERE f.path = ?") + " ORDER BY f.display_name COLLATE NOCASE",
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
                self._folder_aggregate_sql("WHERE f.is_active = 1") + " ORDER BY f.display_name COLLATE NOCASE"
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

    def delete_folder(self, folder_id: int) -> dict[str, list[int]]:
        with self._lock:
            image_ids = [
                int(row["id"])
                for row in self._connection.execute(
                    "SELECT id FROM indexed_images WHERE folder_id = ?",
                    (folder_id,),
                ).fetchall()
            ]
            chunk_ids = [
                int(row["id"])
                for row in self._connection.execute(
                    """
                    SELECT c.id
                    FROM asset_chunks c
                    JOIN indexed_assets a ON a.id = c.asset_id
                    WHERE a.folder_id = ?
                    """,
                    (folder_id,),
                ).fetchall()
            ]
            self._delete_fts_rows_locked(chunk_ids)
            self._connection.execute("DELETE FROM indexed_folders WHERE id = ?", (folder_id,))
            if image_ids:
                self._increment_revision_locked("embeddings_revision")
            if chunk_ids:
                self._increment_revision_locked("text_embeddings_revision")
            self._connection.commit()
        return {"imageIds": image_ids, "textChunkIds": chunk_ids}

    def get_image_by_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_images WHERE path = ?",
                (path,),
            ).fetchone()

    def get_asset_by_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_assets WHERE path = ?",
                (path,),
            ).fetchone()

    def list_documents_missing_previews(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT *
                FROM indexed_assets
                WHERE asset_type = 'document'
                  AND index_status = 'ready'
                  AND (preview_path IS NULL OR preview_path = '')
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def get_image_by_hash(self, content_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                "SELECT * FROM indexed_images WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()

    def get_asset_by_hash(self, content_hash: str, asset_type: str) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(
                """
                SELECT * FROM indexed_assets
                WHERE content_hash = ? AND asset_type = ?
                LIMIT 1
                """,
                (content_hash, asset_type),
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
        return int(self.upsert_images_batch([payload])[payload["path"]])

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
                f"SELECT * FROM indexed_images WHERE path IN ({placeholders})",
                [payload["path"] for payload in payloads],
            ).fetchall()
            mappings = {row["path"]: int(row["id"]) for row in rows}
            self._mirror_images_to_assets_locked(rows)
            self._connection.commit()
        return mappings

    def upsert_assets_batch(self, payloads: Sequence[dict]) -> dict[str, int]:
        if not payloads:
            return {}
        with self._lock:
            mappings = self._upsert_assets_batch_locked(payloads)
            self._connection.commit()
        return mappings

    def replace_asset_chunks(
        self,
        asset_id: int,
        filename: str,
        path: str,
        chunks: Sequence[dict],
    ) -> tuple[list[int], list[tuple[int, dict]]]:
        with self._lock:
            existing_ids = [
                int(row["id"])
                for row in self._connection.execute(
                    "SELECT id FROM asset_chunks WHERE asset_id = ? ORDER BY chunk_index ASC",
                    (asset_id,),
                ).fetchall()
            ]
            self._delete_fts_rows_locked(existing_ids)
            if existing_ids:
                self._connection.execute("DELETE FROM asset_chunks WHERE asset_id = ?", (asset_id,))
            inserted: list[tuple[int, dict]] = []
            for chunk in chunks:
                cursor = self._connection.execute(
                    """
                    INSERT INTO asset_chunks(asset_id, chunk_index, chunk_type, chunk_text, page_number, start_ms, end_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        int(chunk["chunkIndex"]),
                        chunk["chunkType"],
                        chunk["chunkText"],
                        chunk.get("pageNumber"),
                        chunk.get("startMs"),
                        chunk.get("endMs"),
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                self._connection.execute(
                    """
                    INSERT INTO asset_chunks_fts(rowid, filename, chunk_text, path, asset_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chunk_id, filename, chunk["chunkText"], path, asset_id),
                )
                inserted.append((chunk_id, chunk))
            if existing_ids or inserted:
                self._increment_revision_locked("text_embeddings_revision")
            self._connection.commit()
        return existing_ids, inserted

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
            revision = (
                self._increment_revision_locked("embeddings_revision")
                if bump_revision
                else self._read_revision_locked("embeddings_revision")
            )
            self._connection.commit()
        return revision

    def upsert_text_embeddings_batch(
        self,
        records: Sequence[tuple[int, str, np.ndarray, str]],
        *,
        bump_revision: bool = True,
    ) -> int:
        if not records:
            return self.get_text_embeddings_revision()
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO text_embeddings(chunk_id, model_name, vector_dim, vector_blob, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                  model_name = excluded.model_name,
                  vector_dim = excluded.vector_dim,
                  vector_blob = excluded.vector_blob,
                  updated_at = excluded.updated_at
                """,
                [
                    (
                        chunk_id,
                        model_name,
                        int(vector.shape[0]),
                        vector.astype(np.float32).tobytes(),
                        timestamp,
                    )
                    for chunk_id, model_name, vector, timestamp in records
                ],
            )
            revision = (
                self._increment_revision_locked("text_embeddings_revision")
                if bump_revision
                else self._read_revision_locked("text_embeddings_revision")
            )
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

    def iter_embedding_batches(self, batch_size: int) -> Iterator[list[tuple[int, np.ndarray]]]:
        yield from self._iter_vector_batches("embeddings", "image_id", batch_size)

    def iter_text_embedding_batches(self, batch_size: int) -> Iterator[list[tuple[int, np.ndarray]]]:
        yield from self._iter_vector_batches("text_embeddings", "chunk_id", batch_size)

    def list_embedding_ids(self) -> list[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT image_id FROM embeddings ORDER BY image_id"
            ).fetchall()
        return [int(row["image_id"]) for row in rows]

    def get_embeddings_state(self) -> dict[str, int | str | None]:
        return self._get_vector_state("embeddings", "image_id", "embeddings_revision")

    def get_text_embeddings_state(self) -> dict[str, int | str | None]:
        return self._get_vector_state("text_embeddings", "chunk_id", "text_embeddings_revision")

    def get_embeddings_revision(self) -> int:
        with self._lock:
            return self._read_revision_locked("embeddings_revision")

    def get_text_embeddings_revision(self) -> int:
        with self._lock:
            return self._read_revision_locked("text_embeddings_revision")

    def delete_path(self, path: str) -> dict[str, list[int]]:
        with self._lock:
            return self._delete_path_locked(path)

    def prune_folder_assets(self, folder_id: int, seen_paths: set[str]) -> dict[str, list[int]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT path FROM indexed_assets WHERE folder_id = ?",
                (folder_id,),
            ).fetchall()
            removed = {"imageIds": [], "textChunkIds": []}
            for row in rows:
                if row["path"] not in seen_paths:
                    deleted = self._delete_path_locked(row["path"], commit=False)
                    removed["imageIds"].extend(deleted["imageIds"])
                    removed["textChunkIds"].extend(deleted["textChunkIds"])
            if removed["imageIds"] or removed["textChunkIds"]:
                self._connection.commit()
        return removed

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

    def asset_fts_search(
        self,
        query: str,
        asset_type: str,
        folder_ids: Sequence[int] | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        sql = """
        SELECT c.id AS chunk_id, c.asset_id, c.chunk_text, c.page_number, c.start_ms, c.end_ms,
               a.path, a.filename, a.modified_at_fs, a.created_at_fs, a.folder_id, a.asset_type,
               a.preview_path, a.width, a.height, a.duration_ms, f.display_name AS folder_name,
               bm25(asset_chunks_fts) AS text_rank
        FROM asset_chunks_fts
        JOIN asset_chunks c ON c.id = asset_chunks_fts.rowid
        JOIN indexed_assets a ON a.id = c.asset_id
        JOIN indexed_folders f ON f.id = a.folder_id
        WHERE asset_chunks_fts MATCH ?
          AND a.asset_type = ?
        """
        params: list[object] = [query, asset_type]
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            sql += f" AND a.folder_id IN ({placeholders})"
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

    def recent_assets(
        self,
        asset_type: str,
        folder_ids: Sequence[int] | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[sqlite3.Row]:
        order = "DESC" if sort != "oldest" else "ASC"
        sql = """
        SELECT a.*, f.display_name AS folder_name
        FROM indexed_assets a
        JOIN indexed_folders f ON f.id = a.folder_id
        WHERE a.asset_type = ?
        """
        params: list[object] = [asset_type]
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            sql += f" AND a.folder_id IN ({placeholders})"
            params.extend(folder_ids)
        sql += f" ORDER BY a.modified_at_fs {order} LIMIT ? OFFSET ?"
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

    def fetch_assets_by_ids(self, asset_ids: Iterable[int]) -> dict[int, sqlite3.Row]:
        ids = list(dict.fromkeys(int(asset_id) for asset_id in asset_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT a.*, f.display_name AS folder_name
                FROM indexed_assets a
                JOIN indexed_folders f ON f.id = a.folder_id
                WHERE a.id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        return {int(row["id"]): row for row in rows}

    def fetch_chunk_rows_by_ids(
        self,
        chunk_ids: Iterable[int],
        asset_type: str,
        folder_ids: Sequence[int] | None,
    ) -> dict[int, sqlite3.Row]:
        ids = list(dict.fromkeys(int(chunk_id) for chunk_id in chunk_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT c.id AS chunk_id, c.asset_id, c.chunk_text, c.page_number, c.start_ms, c.end_ms,
                   a.path, a.filename, a.modified_at_fs, a.created_at_fs, a.folder_id, a.asset_type,
                   a.preview_path, a.width, a.height, a.duration_ms, f.display_name AS folder_name
            FROM asset_chunks c
            JOIN indexed_assets a ON a.id = c.asset_id
            JOIN indexed_folders f ON f.id = a.folder_id
            WHERE c.id IN ({placeholders}) AND a.asset_type = ?
        """
        params: list[object] = ids + [asset_type]
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            sql += f" AND a.folder_id IN ({placeholders})"
            params.extend(folder_ids)
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return {int(row["chunk_id"]): row for row in rows}

    def fetch_asset_chunks(self, asset_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(
                """
                SELECT *
                FROM asset_chunks
                WHERE asset_id = ?
                ORDER BY chunk_index ASC
                """,
                (asset_id,),
            ).fetchall()

    def update_asset_preview(self, asset_id: int, preview_path: str, last_indexed_at: str | None = None) -> None:
        with self._lock:
            if last_indexed_at:
                self._connection.execute(
                    """
                    UPDATE indexed_assets
                    SET preview_path = ?, last_indexed_at = ?
                    WHERE id = ?
                    """,
                    (preview_path, last_indexed_at, asset_id),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE indexed_assets
                    SET preview_path = ?
                    WHERE id = ?
                    """,
                    (preview_path, asset_id),
                )
            self._connection.commit()

    def _ensure_image_asset_backfill_locked(self) -> None:
        if self._read_setting_locked(IMAGE_ASSET_BACKFILL_KEY) == IMAGE_ASSET_BACKFILL_VERSION:
            return

        rows = self._connection.execute(
            """
            SELECT *
            FROM indexed_images
            ORDER BY id ASC
            """
        ).fetchall()
        if rows:
            self._mirror_images_to_assets_locked(rows)
        self._write_setting_locked(IMAGE_ASSET_BACKFILL_KEY, IMAGE_ASSET_BACKFILL_VERSION)

    def _mirror_images_to_assets_locked(self, rows: Sequence[sqlite3.Row]) -> None:
        payloads = [
            {
                "folder_id": int(row["folder_id"]),
                "asset_type": "image",
                "path": row["path"],
                "filename": row["filename"],
                "extension": row["extension"],
                "content_hash": row["content_hash"],
                "created_at_fs": row["created_at_fs"],
                "modified_at_fs": row["modified_at_fs"],
                "file_size_bytes": int(row["file_size_bytes"]),
                "width": row["width"],
                "height": row["height"],
                "duration_ms": None,
                "preview_path": row["thumbnail_path"],
                "last_indexed_at": row["last_indexed_at"],
                "index_status": row["index_status"],
                "error_code": row["error_code"],
                "error_message": row["error_message"],
            }
            for row in rows
        ]
        asset_ids_by_path = self._upsert_assets_batch_locked(payloads)
        for row in rows:
            asset_id = asset_ids_by_path.get(row["path"])
            if asset_id is None:
                continue
            ocr_text = (row["ocr_text"] or "").strip()
            chunks = (
                [
                    {
                        "chunkIndex": 0,
                        "chunkType": "ocr",
                        "chunkText": ocr_text,
                        "pageNumber": None,
                        "startMs": None,
                        "endMs": None,
                    }
                ]
                if ocr_text
                else []
            )
            self._replace_asset_chunks_locked(asset_id, row["filename"], row["path"], chunks)

    def _upsert_assets_batch_locked(self, payloads: Sequence[dict]) -> dict[str, int]:
        self._connection.executemany(
            """
            INSERT INTO indexed_assets(
              folder_id, asset_type, path, filename, extension, content_hash, created_at_fs, modified_at_fs,
              file_size_bytes, width, height, duration_ms, preview_path,
              last_indexed_at, index_status, error_code, error_message
            )
            VALUES (
              :folder_id, :asset_type, :path, :filename, :extension, :content_hash, :created_at_fs, :modified_at_fs,
              :file_size_bytes, :width, :height, :duration_ms, :preview_path,
              :last_indexed_at, :index_status, :error_code, :error_message
            )
            ON CONFLICT(path) DO UPDATE SET
              folder_id = excluded.folder_id,
              asset_type = excluded.asset_type,
              filename = excluded.filename,
              extension = excluded.extension,
              content_hash = excluded.content_hash,
              created_at_fs = excluded.created_at_fs,
              modified_at_fs = excluded.modified_at_fs,
              file_size_bytes = excluded.file_size_bytes,
              width = excluded.width,
              height = excluded.height,
              duration_ms = excluded.duration_ms,
              preview_path = excluded.preview_path,
              last_indexed_at = excluded.last_indexed_at,
              index_status = excluded.index_status,
              error_code = excluded.error_code,
              error_message = excluded.error_message
            """,
            payloads,
        )
        placeholders = ",".join("?" for _ in payloads)
        rows = self._connection.execute(
            f"SELECT id, path FROM indexed_assets WHERE path IN ({placeholders})",
            [payload["path"] for payload in payloads],
        ).fetchall()
        return {row["path"]: int(row["id"]) for row in rows}

    def _replace_asset_chunks_locked(
        self,
        asset_id: int,
        filename: str,
        path: str,
        chunks: Sequence[dict],
    ) -> list[tuple[int, dict]]:
        existing_ids = [
            int(row["id"])
            for row in self._connection.execute(
                "SELECT id FROM asset_chunks WHERE asset_id = ? ORDER BY chunk_index ASC",
                (asset_id,),
            ).fetchall()
        ]
        self._delete_fts_rows_locked(existing_ids)
        if existing_ids:
            self._connection.execute("DELETE FROM asset_chunks WHERE asset_id = ?", (asset_id,))
        inserted: list[tuple[int, dict]] = []
        for chunk in chunks:
            cursor = self._connection.execute(
                """
                INSERT INTO asset_chunks(asset_id, chunk_index, chunk_type, chunk_text, page_number, start_ms, end_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    int(chunk["chunkIndex"]),
                    chunk["chunkType"],
                    chunk["chunkText"],
                    chunk.get("pageNumber"),
                    chunk.get("startMs"),
                    chunk.get("endMs"),
                ),
            )
            chunk_id = int(cursor.lastrowid)
            self._connection.execute(
                """
                INSERT INTO asset_chunks_fts(rowid, filename, chunk_text, path, asset_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chunk_id, filename, chunk["chunkText"], path, asset_id),
            )
            inserted.append((chunk_id, chunk))
        return inserted

    def _delete_path_locked(self, path: str, *, commit: bool = True) -> dict[str, list[int]]:
        asset_row = self._connection.execute(
            "SELECT id, asset_type FROM indexed_assets WHERE path = ?",
            (path,),
        ).fetchone()
        image_row = self._connection.execute(
            "SELECT id FROM indexed_images WHERE path = ?",
            (path,),
        ).fetchone()
        chunk_ids: list[int] = []
        if asset_row:
            chunk_ids = [
                int(row["id"])
                for row in self._connection.execute(
                    "SELECT id FROM asset_chunks WHERE asset_id = ?",
                    (asset_row["id"],),
                ).fetchall()
            ]
            self._delete_fts_rows_locked(chunk_ids)
            self._connection.execute("DELETE FROM indexed_assets WHERE path = ?", (path,))
        if image_row:
            self._connection.execute("DELETE FROM indexed_images WHERE path = ?", (path,))
        if image_row:
            self._increment_revision_locked("embeddings_revision")
        if chunk_ids:
            self._increment_revision_locked("text_embeddings_revision")
        if commit:
            self._connection.commit()
        return {
            "imageIds": [int(image_row["id"])] if image_row else [],
            "textChunkIds": chunk_ids,
        }

    def _delete_fts_rows_locked(self, chunk_ids: Sequence[int]) -> None:
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        self._connection.execute(
            f"DELETE FROM asset_chunks_fts WHERE rowid IN ({placeholders})",
            list(chunk_ids),
        )

    def _iter_vector_batches(
        self,
        table_name: str,
        id_column: str,
        batch_size: int,
    ) -> Iterator[list[tuple[int, np.ndarray]]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        with self._lock:
            cursor = self._connection.execute(
                f"""
                SELECT {id_column} AS item_id, vector_blob
                FROM {table_name}
                ORDER BY {id_column} ASC
                """
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                yield [
                    (int(row["item_id"]), np.frombuffer(row["vector_blob"], dtype=np.float32))
                    for row in rows
                ]

    def _get_vector_state(
        self,
        table_name: str,
        id_column: str,
        revision_key: str,
    ) -> dict[str, int | str | None]:
        with self._lock:
            row = self._connection.execute(
                f"""
                SELECT COUNT(*) AS count,
                       MIN(model_name) AS model_name,
                       MAX(vector_dim) AS vector_dim
                FROM {table_name}
                """
            ).fetchone()
            revision = self._read_revision_locked(revision_key)
        return {
            "revision": revision,
            "count": int(row["count"] or 0),
            "model_name": row["model_name"],
            "vector_dim": int(row["vector_dim"]) if row["vector_dim"] is not None else None,
        }

    def _ensure_revision_locked(self, key: str) -> None:
        self._connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES (?, '0', 'system')
            ON CONFLICT(key) DO NOTHING
            """,
            (key,),
        )

    def _read_revision_locked(self, key: str) -> int:
        self._ensure_revision_locked(key)
        row = self._connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            (key,),
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

    def _increment_revision_locked(self, key: str) -> int:
        revision = self._read_revision_locked(key) + 1
        self._connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES (?, ?, 'system')
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (key, json.dumps(revision)),
        )
        return revision

    def _read_setting_locked(self, key: str) -> int | None:
        row = self._connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
        if not row or row["value_json"] is None:
            return None
        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            try:
                return int(row["value_json"])
            except (TypeError, ValueError):
                return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _write_setting_locked(self, key: str, value: int) -> None:
        self._connection.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES (?, ?, 'system')
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (key, json.dumps(value)),
        )

    @staticmethod
    def _folder_aggregate_sql(suffix: str) -> str:
        return f"""
            SELECT f.id, f.path, f.display_name, f.is_active,
                   COUNT(a.id) AS item_count,
                   SUM(CASE WHEN a.asset_type = 'image' THEN 1 ELSE 0 END) AS image_count,
                   SUM(CASE WHEN a.asset_type = 'document' THEN 1 ELSE 0 END) AS document_count,
                   SUM(CASE WHEN a.asset_type = 'voice-note' THEN 1 ELSE 0 END) AS voice_note_count,
                   MAX(a.last_indexed_at) AS last_indexed_at
            FROM indexed_folders f
            LEFT JOIN indexed_assets a ON a.folder_id = f.id
            {suffix}
            GROUP BY f.id
        """

    @staticmethod
    def _folder_row(row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "path": row["path"],
            "displayName": row["display_name"],
            "isActive": bool(row["is_active"]),
            "itemCount": int(row["item_count"] or 0),
            "imageCount": int(row["image_count"] or 0),
            "documentCount": int(row["document_count"] or 0),
            "voiceNoteCount": int(row["voice_note_count"] or 0),
            "lastIndexedAt": row["last_indexed_at"],
        }

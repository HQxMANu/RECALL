# Recall SQLite Schema

## Tables

### `indexed_folders`
- `id INTEGER PRIMARY KEY`
- `path TEXT UNIQUE NOT NULL`
- `display_name TEXT NOT NULL`
- `is_active INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### `indexed_images`
- `id INTEGER PRIMARY KEY`
- `folder_id INTEGER NOT NULL`
- `path TEXT UNIQUE NOT NULL`
- `filename TEXT NOT NULL`
- `extension TEXT NOT NULL`
- `content_hash TEXT NOT NULL`
- `created_at_fs TEXT`
- `modified_at_fs TEXT NOT NULL`
- `file_size_bytes INTEGER NOT NULL`
- `width INTEGER`
- `height INTEGER`
- `ocr_text TEXT`
- `thumbnail_path TEXT`
- `last_indexed_at TEXT NOT NULL`
- `index_status TEXT NOT NULL`
- `error_code TEXT`
- `error_message TEXT`

### `embeddings`
- `image_id INTEGER PRIMARY KEY`
- `model_name TEXT NOT NULL`
- `vector_dim INTEGER NOT NULL`
- `vector_blob BLOB NOT NULL`
- `updated_at TEXT NOT NULL`

### `indexed_images_fts`
- FTS5 table over `filename`, `ocr_text`, `path`
- Maintained through insert, update, and delete triggers

### `indexing_jobs`
- Tracks background full-index and watcher-triggered jobs

### `app_settings`
- Simple key-value JSON settings table

## Indexes

- `idx_images_folder_id`
- `idx_images_modified`
- `idx_images_hash`
- `idx_images_status`
- `idx_jobs_status`
- `idx_jobs_started_at`

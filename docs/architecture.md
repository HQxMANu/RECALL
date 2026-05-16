# Recall Architecture

Recall uses a three-layer local architecture:

1. `React + Tauri UI`
   - Search bar, sidebar, result grid, preview modal
   - Polls indexing status and health
   - Invokes Rust commands only

2. `Tauri Rust host`
   - Opens native folder picker
   - Launches the Python worker once at startup
   - Forwards typed requests over JSON lines on stdio
   - Runs debounced filesystem watchers and pushes file events to the worker
   - Handles privileged desktop actions such as `explorer /select` and clipboard writes

3. `Python worker`
   - Owns SQLite writes and schema
   - Indexes supported images recursively
   - Generates thumbnails
   - Extracts OCR text
   - Creates embeddings
   - Maintains vector search state
   - Returns hybrid search results

## Runtime flow

- User adds folders in the UI.
- Tauri sends `add_folders` to the worker.
- Worker stores folders, queues a background indexing job, and replies immediately.
- UI polls `get_indexing_status`.
- Search requests hit both FTS5 and the vector index, then run through the hybrid ranker.

## Local-first guarantees

- No cloud APIs
- No telemetry
- No remote inference
- All data stored under the app data directory passed to the worker

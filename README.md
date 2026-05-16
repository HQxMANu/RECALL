# Recall

Recall is a Windows-first, local-only screenshot and image search app built with:

- `Tauri`
- `React + TypeScript`
- `Python`
- `SQLite + FTS5`
- `FAISS` when installed, with a local NumPy fallback during development

## What is implemented

- Desktop app shell with Spotlight-style search layout
- Folder selection, folder filtering, and removal
- Long-lived Python worker launched by the Tauri host
- SQLite schema for folders, images, embeddings, jobs, and settings
- OCR service abstraction with `PaddleOCR -> Tesseract -> null` fallback chain
- Embedding service abstraction with `OpenCLIP -> hash fallback`
- Vector search abstraction with `FAISS -> NumPy fallback`
- Thumbnail generation
- Incremental reprocessing from filesystem watcher events
- Preview modal, open location, and copy path actions
- Unit tests for ranking, database schema, and fallback embeddings

## Local setup

1. Install Node.js, Python 3.11+, the Rust toolchain, and Visual Studio Build Tools with the C++ workload for Windows linking.
2. Install frontend dependencies:

```powershell
npm install
```

3. Create the optional Python environment for the worker:

```powershell
cd python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
pip install ".[ml]"
cd ..
```

4. Run the desktop app:

```powershell
npm run dev:tauri
```

## Validation

- Frontend typecheck: `npm run typecheck`
- Frontend lint: `npm run lint`
- Python tests: `python -m unittest discover -s python/tests -t python`
- Packaging smoke test: `.\scripts\smoke-test.ps1`

## Notes

- The repository is intentionally local-first. There are no network calls in the runtime path.
- If the optional ML packages are not installed, Recall still runs using local fallback engines and surfaces that degraded state in the UI.

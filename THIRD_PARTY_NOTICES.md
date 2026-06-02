# Third-Party Notices

Recall redistributes and depends on a number of third-party open-source components.

Major runtime components currently include:

- Tauri
- React
- SQLite / rusqlite
- Python 3.11 runtime
- Torch
- FAISS
- Paddle / PaddleOCR
- Faster-Whisper
- Transformers / Hugging Face ecosystem components
- Pillow
- NumPy / SciPy

Each component remains subject to its own upstream license terms.

## Practical Guidance

- review the dependency manifests in `package.json`, `src-tauri/Cargo.toml`, and `python/pyproject.toml`
- review packaged dependency metadata inside the staged Python runtime if you publish convenience binaries
- keep this notice updated when major redistributed runtime dependencies change

This file is a project-level notice, not a substitute for upstream license terms.

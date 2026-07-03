# Recall Architecture

Recall is a Windows-first, local-first desktop search application for screenshots and images. It is designed to let users search their visual history in plain English without sending files, OCR text, or embeddings to external services.

The system is intentionally split into three layers so the UI stays responsive, desktop-specific actions stay isolated, and indexing and search workloads can run independently.

## Design goals

Recall is built around four core goals:

- Keep all user data and search processing local to the machine
- Separate UI concerns from filesystem and indexing concerns
- Allow long-running indexing work without blocking the desktop interface
- Make search results fast, explainable, and resilient as the local dataset grows

## High-level architecture

Recall uses a three-layer architecture:

1. `React + Tauri UI`
2. `Rust desktop host`
3. `Python indexing and search worker`

Each layer has a narrow responsibility boundary.

## Layer responsibilities

### 1. React + Tauri UI

The frontend is responsible for user interaction and application state presentation.

Responsibilities:

- Render the search bar, results grid, preview modal, and status surfaces
- Show indexing progress and readiness state
- Trigger user actions such as folder selection, search, preview, and open-location actions
- Poll for worker status and display errors or degraded states clearly
- Communicate only through Tauri commands

The UI does not read the filesystem directly, perform OCR, manage embeddings, or write to SQLite. Its job is to remain responsive and act as a clean control surface over the underlying local engine.

### 2. Rust desktop host

The Rust host acts as the desktop integration and orchestration layer between the UI and the worker.

Responsibilities:

- Expose safe desktop commands to the frontend through Tauri
- Open native folder pickers
- Launch the Python worker once at startup
- Send requests to the worker over JSON lines on stdio
- Watch indexed folders for filesystem changes
- Debounce and forward file events to the worker
- Handle privileged desktop actions such as `explorer /select` and clipboard writes

This layer exists to isolate OS-specific behavior and process management from the frontend. It also provides a stable boundary so the UI never needs direct access to low-level desktop or filesystem operations.

### 3. Python indexing and search worker

The Python worker is the search engine and indexing core of the application.

Responsibilities:

- Own SQLite writes and schema management
- Track indexed folders and indexing jobs
- Scan local assets recursively
- Extract OCR text from images
- Generate thumbnails
- Create and store embeddings
- Maintain vector-search state
- Execute text search, semantic search, and hybrid ranking
- Return structured search results to the host

The worker is intentionally separated from the desktop shell because indexing and search are long-running, stateful tasks that benefit from an isolated process boundary.

## Communication model

The system uses a request-response model between the Rust host and Python worker over JSON lines on stdio.

Why this matters:

- The contract is explicit and inspectable
- The worker can evolve independently from the UI
- Failures in indexing logic are easier to isolate from the desktop shell
- Search and indexing logic can be tested with less coupling to the frontend

The frontend never talks to the worker directly. All requests pass through the Rust host.

## Runtime flow

A typical runtime flow looks like this:

1. The user adds one or more folders from the UI.
2. The frontend calls a Tauri command.
3. The Rust host forwards an `add_folders` request to the worker.
4. The worker stores the folder metadata and queues a background indexing job.
5. The UI polls `get_indexing_status` to show readiness and progress.
6. When the user searches, the request is passed through the host to the worker.
7. The worker runs text and semantic retrieval, combines the results, and returns ranked matches.
8. The UI renders results, previews, and quick actions.

This design keeps expensive local processing off the main interface while still giving the user clear feedback about system state.

## Indexing pipeline

The indexing pipeline is responsible for turning raw local image files into searchable records.

At a high level it:

- discovers files from indexed folders
- stores file metadata in SQLite
- generates thumbnails for fast preview
- extracts OCR text where available
- creates embeddings for semantic retrieval
- updates index state and job progress
- responds to later filesystem changes through watcher-triggered updates

This allows Recall to support both first-time indexing and ongoing incremental maintenance.

## Search pipeline

Recall uses hybrid retrieval instead of relying on only one search method.

Search combines:

- exact and partial text matches through SQLite FTS
- OCR-derived text matches
- semantic similarity from local embeddings
- ranking logic that balances relevance and recency

This hybrid approach improves result quality for both filename-based and meaning-based queries.

## Local-first guarantees

Recall is designed so core user data remains on-device.

Current guarantees:

- No cloud APIs in the runtime path
- No telemetry in the current runtime
- No remote inference
- All indexed content is stored in local app data
- Search, OCR, and ranking operate within the local system boundary

This local-first model is a product decision, not just an implementation detail. Privacy, offline usefulness, and control over personal data are central to the architecture.

## Tradeoffs

This architecture intentionally accepts some complexity in exchange for stronger separation of concerns.

Key tradeoffs:

- Multi-process coordination is more complex than a single-process app
- JSON-based IPC adds protocol surface that must stay stable
- Worker lifecycle and error handling need to be managed carefully
- In return, the UI stays cleaner, desktop actions stay isolated, and search and indexing logic can scale more safely

## Why this architecture fits Recall

Recall is not just a UI over a search box. It is a desktop product that combines local indexing, OCR, semantic retrieval, and native system actions. Splitting the system into UI, host, and worker layers keeps those concerns separate and makes the product easier to reason about, extend, and harden over time.

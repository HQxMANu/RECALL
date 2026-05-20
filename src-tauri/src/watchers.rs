use std::{
    any::Any,
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::Duration,
};

use anyhow::Context;
use log::{error, warn};
use notify_debouncer_mini::{new_debouncer, notify::RecursiveMode, DebouncedEventKind};

use crate::{
    models::{FsEventPayload, IndexedFolder},
    process::WorkerClient,
};

#[derive(Clone, Default)]
pub struct WatchService {
    guard: Arc<Mutex<Option<Box<dyn Any + Send>>>>,
}

#[derive(Default)]
struct PendingDispatchState {
    pending: BTreeMap<String, FsEventPayload>,
    active: bool,
    merged_events: u64,
    coalesced_events: u64,
    dispatched_events: u64,
}

impl WatchService {
    pub fn rebuild(&self, folders: &[IndexedFolder], worker: WorkerClient) -> Result<(), String> {
        let (tx, rx) = mpsc::channel();
        let mut debouncer =
            new_debouncer(Duration::from_millis(800), tx).map_err(|error| error.to_string())?;

        for folder in folders.iter().filter(|folder| folder.is_active) {
            debouncer
                .watcher()
                .watch(Path::new(&folder.path), RecursiveMode::Recursive)
                .map_err(|error| error.to_string())?;
        }

        let dispatch_state = Arc::new(Mutex::new(PendingDispatchState::default()));
        let dispatch_worker = worker.clone();
        thread::Builder::new()
            .name("recall-watch-dispatch".to_string())
            .spawn(move || {
                while let Ok(result) = rx.recv() {
                    match result {
                        Ok(events) => {
                            let payload = events
                                .into_iter()
                                .filter_map(|event| normalize_event(event.kind, &event.path))
                                .collect::<Vec<_>>();

                            if payload.is_empty() {
                                continue;
                            }

                            let mut should_spawn = false;
                            if let Ok(mut state) = dispatch_state.lock() {
                                for event in payload {
                                    merge_event(&mut state, event);
                                }
                                if !state.active && !state.pending.is_empty() {
                                    state.active = true;
                                    should_spawn = true;
                                }
                            }

                            if should_spawn {
                                spawn_dispatch_loop(dispatch_state.clone(), dispatch_worker.clone());
                            }
                        }
                        Err(error) => error!("Filesystem watcher error: {error:?}"),
                    }
                }
            })
            .context("Failed to spawn watcher dispatch thread")
            .map_err(|error| error.to_string())?;

        let mut guard = self
            .guard
            .lock()
            .map_err(|_| "Failed to update watch service".to_string())?;
        *guard = Some(Box::new(debouncer));
        Ok(())
    }
}

fn spawn_dispatch_loop(
    state: Arc<Mutex<PendingDispatchState>>,
    worker: WorkerClient,
) {
    tauri::async_runtime::spawn(async move {
        loop {
            let events = {
                let Ok(mut pending_state) = state.lock() else {
                    return;
                };
                if pending_state.pending.is_empty() {
                    pending_state.active = false;
                    return;
                }
                let events = pending_state.pending.values().cloned().collect::<Vec<_>>();
                pending_state.pending.clear();
                pending_state.dispatched_events += events.len() as u64;
                events
            };

            if let Err(error) = worker
                .request::<_, serde_json::Value>(
                    "process_fs_events",
                    serde_json::json!({ "events": events }),
                )
                .await
            {
                warn!("Failed to forward filesystem events to Python worker: {error}");
            }
        }
    });
}

fn merge_event(state: &mut PendingDispatchState, event: FsEventPayload) {
    match state.pending.get_mut(&event.path) {
        Some(existing) => {
            state.coalesced_events += 1;
            if existing.kind == "delete" {
                return;
            }
            if event.kind == "delete" {
                existing.kind = "delete".to_string();
            }
        }
        None => {
            state.pending.insert(event.path.clone(), event);
            state.merged_events += 1;
        }
    }
}

fn normalize_event(kind: DebouncedEventKind, path: &Path) -> Option<FsEventPayload> {
    let normalized_path = normalize_path(path)?;
    let event_kind = match kind {
        DebouncedEventKind::AnyContinuous => "modify",
        DebouncedEventKind::Any => {
            if Path::new(&normalized_path).exists() {
                "modify"
            } else {
                "delete"
            }
        }
        _ => "modify",
    };

    Some(FsEventPayload {
        kind: event_kind.to_string(),
        path: normalized_path,
    })
}

fn normalize_path(path: &Path) -> Option<String> {
    let candidate = PathBuf::from(path);
    let normalized = if candidate.exists() {
        fs::canonicalize(&candidate).ok()?
    } else {
        candidate
    };
    Some(normalized.to_string_lossy().to_string())
}

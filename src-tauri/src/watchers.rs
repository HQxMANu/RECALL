use std::{
    any::Any,
    path::Path,
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

        thread::Builder::new()
      .name("recall-watch-dispatch".to_string())
      .spawn(move || {
        while let Ok(result) = rx.recv() {
          match result {
            Ok(events) => {
              let payload = events
                .into_iter()
                .map(|event| FsEventPayload {
                  kind: match event.kind {
                    DebouncedEventKind::AnyContinuous => "modify".to_string(),
                    DebouncedEventKind::Any => {
                      if Path::new(&event.path).exists() {
                        "modify".to_string()
                      } else {
                        "delete".to_string()
                      }
                    }
                    _ => "modify".to_string(),
                  },
                  path: event.path.to_string_lossy().to_string(),
                })
                .collect::<Vec<_>>();

              if payload.is_empty() {
                continue;
              }

              let worker = worker.clone();
              tauri::async_runtime::spawn(async move {
                if let Err(error) = worker.request::<_, serde_json::Value>(
                  "process_fs_events",
                  serde_json::json!({ "events": payload }),
                )
                .await
                {
                  warn!("Failed to forward filesystem events to Python worker: {error}");
                }
              });
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

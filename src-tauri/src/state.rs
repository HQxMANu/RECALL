use std::{
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};

use anyhow::Context;
use tauri::{AppHandle, Emitter, Manager};

use crate::{
    local_data,
    models::{AppHealth, IndexedFolder, IndexingStatus, SearchRequest, SearchResponse},
    process::WorkerClient,
    watchers::WatchService,
};

#[derive(Clone)]
pub struct AppState {
    pub worker: WorkerManager,
    pub watchers: WatchService,
    pub app_data_dir: PathBuf,
}

impl AppState {
    pub fn new(app: &AppHandle) -> anyhow::Result<Self> {
        let app_data_dir = resolve_app_data_dir(app)?;
        fs::create_dir_all(&app_data_dir).context("Failed to create app data directory")?;
        let worker_root = crate::process::worker_root(app, &app_data_dir)?;

        Ok(Self {
            worker: WorkerManager::new(worker_root, app_data_dir.clone()),
            watchers: WatchService::default(),
            app_data_dir,
        })
    }

    pub fn prewarm_worker(&self) {
        self.worker.start_in_background();
    }

    pub fn start_event_bridge(&self, app: AppHandle) {
        let state = self.clone();
        tauri::async_runtime::spawn(async move {
            let mut last_health = None;
            let mut last_status = None;
            let mut last_folders = None;

            loop {
                let current_health = state.get_app_health().await.ok();
                if let Some(health) = current_health.as_ref() {
                    let serialized = serde_json::to_string(&health).ok();
                    if serialized != last_health {
                        let _ = app.emit("recall://health", &health);
                        last_health = serialized;
                    }
                }

                let current_status = state.read_indexing_status().ok();
                if let Some(status) = current_status.as_ref() {
                    let serialized = serde_json::to_string(&status).ok();
                    if serialized != last_status {
                        let _ = app.emit("recall://indexing-status", &status);
                        last_status = serialized;
                    }
                }

                if let Ok(folders) = state.list_indexed_folders() {
                    let serialized = serde_json::to_string(&folders).ok();
                    if serialized != last_folders {
                        let _ = app.emit("recall://folders-changed", &folders);
                        last_folders = serialized;
                    }
                }

                let interval = event_bridge_interval(current_status.as_ref(), current_health.as_ref());
                tokio::time::sleep(interval).await;
            }
        });
    }

    pub async fn sync_watched_folders(&self) -> Result<(), String> {
        let folders = self.list_indexed_folders()?;
        let worker = self.worker.client().await?;
        self.watchers.rebuild(&folders, worker)
    }

    pub fn list_indexed_folders(&self) -> Result<Vec<IndexedFolder>, String> {
        local_data::list_indexed_folders(&self.app_data_dir).map_err(|error| error.to_string())
    }

    pub fn read_indexing_status(&self) -> Result<IndexingStatus, String> {
        local_data::read_indexing_status(&self.app_data_dir).map_err(|error| error.to_string())
    }

    pub fn search_recent_images(&self, request: &SearchRequest) -> Result<SearchResponse, String> {
        local_data::search_recent_images(&self.app_data_dir, request)
            .map_err(|error| error.to_string())
    }

    pub async fn get_app_health(&self) -> Result<AppHealth, String> {
        if !self.worker.is_ready() {
            return Ok(self
                .worker
                .health_snapshot(self.app_data_dir.join("recall.db").exists()));
        }

        let worker = self.worker.client().await?;
        worker
            .request("get_health", serde_json::json!({}))
            .await
            .or_else(|error| {
                self.worker.mark_failed(&error);
                Ok(self
                    .worker
                    .health_snapshot(self.app_data_dir.join("recall.db").exists()))
            })
    }

    pub async fn emit_current_snapshots(&self, app: &AppHandle) -> Result<(), String> {
        let folders = self.list_indexed_folders()?;
        let status = self.read_indexing_status()?;
        let health = self.get_app_health().await?;

        app.emit("recall://folders-changed", &folders)
            .map_err(|error| error.to_string())?;
        app.emit("recall://indexing-status", &status)
            .map_err(|error| error.to_string())?;
        app.emit("recall://health", &health)
            .map_err(|error| error.to_string())?;
        Ok(())
    }
}

#[derive(Clone)]
pub struct WorkerManager {
    inner: Arc<WorkerManagerInner>,
}

struct WorkerManagerInner {
    worker_root: PathBuf,
    app_data_dir: PathBuf,
    state: Mutex<WorkerManagerState>,
}

struct WorkerManagerState {
    phase: WorkerPhase,
    client: Option<WorkerClient>,
}

#[derive(Clone)]
enum WorkerPhase {
    NotStarted,
    Starting,
    Ready,
    Failed(String),
}

impl WorkerManager {
    pub fn new(worker_root: PathBuf, app_data_dir: PathBuf) -> Self {
        Self {
            inner: Arc::new(WorkerManagerInner {
                worker_root,
                app_data_dir,
                state: Mutex::new(WorkerManagerState {
                    phase: WorkerPhase::NotStarted,
                    client: None,
                }),
            }),
        }
    }

    pub fn start_in_background(&self) {
        if !self.begin_start() {
            return;
        }

        let manager = self.clone();
        tauri::async_runtime::spawn(async move {
            if let Err(error) = manager.spawn_worker().await {
                manager.mark_failed(&error);
            }
        });
    }

    pub async fn client(&self) -> Result<WorkerClient, String> {
        if let Some(client) = self.current_client() {
            return Ok(client);
        }

        if self.begin_start() {
            self.spawn_worker().await?;
        }

        self.wait_for_client().await
    }

    pub fn is_ready(&self) -> bool {
        self.inner
            .state
            .lock()
            .map(|state| matches!(state.phase, WorkerPhase::Ready))
            .unwrap_or(false)
    }

    pub fn mark_failed(&self, error: &str) {
        if let Ok(mut state) = self.inner.state.lock() {
            if let Some(client) = state.client.take() {
                client.terminate();
            }
            state.phase = WorkerPhase::Failed(error.to_string());
        }
    }

    pub fn health_snapshot(&self, database_ready: bool) -> AppHealth {
        let phase = self
            .inner
            .state
            .lock()
            .map(|state| state.phase.clone())
            .unwrap_or(WorkerPhase::Failed("Worker state lock failed.".to_string()));

        match phase {
            WorkerPhase::Ready => AppHealth {
                worker_ready: true,
                database_ready,
                text_search_ready: true,
                semantic_search_ready: false,
                core_search_ready: false,
                core_search_phase: "warming".to_string(),
                core_search_message: "Recall is verifying semantic and text search startup."
                    .to_string(),
                indexing_phase: "deferred".to_string(),
                indexing_message: "OCR stays deferred until indexing starts.".to_string(),
                vector_engine: "warming".to_string(),
                ocr_engine: "deferred".to_string(),
                embedding_engine: "warming".to_string(),
                degraded: true,
                message: "Core search is warming in the background.".to_string(),
                startup_metrics: None,
            },
            WorkerPhase::Failed(error) => AppHealth {
                worker_ready: false,
                database_ready,
                text_search_ready: false,
                semantic_search_ready: false,
                core_search_ready: false,
                core_search_phase: "error".to_string(),
                core_search_message: format!("Core search failed to start: {error}"),
                indexing_phase: "deferred".to_string(),
                indexing_message: "OCR stays deferred until indexing starts.".to_string(),
                vector_engine: "unavailable".to_string(),
                ocr_engine: "deferred".to_string(),
                embedding_engine: "unavailable".to_string(),
                degraded: true,
                message: format!("Local AI failed to start: {error}"),
                startup_metrics: None,
            },
            WorkerPhase::NotStarted | WorkerPhase::Starting => AppHealth {
                worker_ready: false,
                database_ready,
                text_search_ready: false,
                semantic_search_ready: false,
                core_search_ready: false,
                core_search_phase: "warming".to_string(),
                core_search_message:
                    "Recall is warming semantic + text search together before enabling search."
                        .to_string(),
                indexing_phase: "deferred".to_string(),
                indexing_message: "OCR stays deferred until indexing starts.".to_string(),
                vector_engine: "warming".to_string(),
                ocr_engine: "deferred".to_string(),
                embedding_engine: "warming".to_string(),
                degraded: true,
                message: "Shell is ready. Core search is warming in the background.".to_string(),
                startup_metrics: None,
            },
        }
    }

    async fn spawn_worker(&self) -> Result<(), String> {
        let worker_root = self.inner.worker_root.clone();
        let app_data_dir = self.inner.app_data_dir.clone();

        let client = tauri::async_runtime::spawn_blocking(move || {
            WorkerClient::new(&worker_root, &app_data_dir).map_err(|error| error.to_string())
        })
        .await
        .map_err(|error| error.to_string())??;

        if let Ok(mut state) = self.inner.state.lock() {
            state.client = Some(client.clone());
            state.phase = WorkerPhase::Starting;
        }

        let manager = self.clone();
        tauri::async_runtime::spawn(async move {
            match tokio::time::timeout(Duration::from_secs(30), client.ping()).await {
                Ok(Ok(())) => {
                    if let Ok(mut state) = manager.inner.state.lock() {
                        state.phase = WorkerPhase::Ready;
                    }
                }
                Ok(Err(error)) => manager.mark_failed(&error),
                Err(_) => manager.mark_failed(
                    "Timed out while waiting for core search services to finish startup.",
                ),
            }
        });

        Ok(())
    }

    async fn wait_for_client(&self) -> Result<WorkerClient, String> {
        for _ in 0..80 {
            if let Some(client) = self.current_client() {
                return Ok(client);
            }

            if let Some(error) = self.failure_message() {
                return Err(error);
            }

            tokio::time::sleep(Duration::from_millis(25)).await;
        }

        Err("Timed out while starting the local worker.".to_string())
    }

    fn begin_start(&self) -> bool {
        let Ok(mut state) = self.inner.state.lock() else {
            return false;
        };

        if state.client.is_some()
            || matches!(state.phase, WorkerPhase::Starting | WorkerPhase::Ready)
        {
            return false;
        }

        state.phase = WorkerPhase::Starting;
        true
    }

    fn current_client(&self) -> Option<WorkerClient> {
        self.inner
            .state
            .lock()
            .ok()
            .and_then(|state| state.client.clone())
    }

    fn failure_message(&self) -> Option<String> {
        self.inner
            .state
            .lock()
            .ok()
            .and_then(|state| match &state.phase {
                WorkerPhase::Failed(error) => Some(error.clone()),
                _ => None,
            })
    }
}

fn resolve_app_data_dir(app: &AppHandle) -> anyhow::Result<PathBuf> {
    app.path()
        .app_data_dir()
        .context("Unable to resolve the app data directory")
}

fn event_bridge_interval(
    status: Option<&IndexingStatus>,
    health: Option<&AppHealth>,
) -> Duration {
    if matches!(health, Some(health) if !health.core_search_ready) {
        return Duration::from_millis(500);
    }
    if matches!(status, Some(status) if status.state == "indexing") {
        return Duration::from_secs(2);
    }
    Duration::from_secs(15)
}

#[cfg(test)]
mod tests {
    use super::event_bridge_interval;
    use crate::models::{AppHealth, IndexingStatus};
    use std::time::Duration;

    fn ready_health() -> AppHealth {
        AppHealth {
            worker_ready: true,
            database_ready: true,
            text_search_ready: true,
            semantic_search_ready: true,
            core_search_ready: true,
            core_search_phase: "ready".to_string(),
            core_search_message: "ready".to_string(),
            indexing_phase: "deferred".to_string(),
            indexing_message: "deferred".to_string(),
            vector_engine: "faiss".to_string(),
            ocr_engine: "deferred".to_string(),
            embedding_engine: "openclip".to_string(),
            degraded: false,
            message: "ready".to_string(),
            startup_metrics: None,
        }
    }

    fn indexing_status(state: &str) -> IndexingStatus {
        IndexingStatus {
            state: state.to_string(),
            active_job_id: None,
            active_job_type: None,
            items_total: 0,
            items_processed: 0,
            queued_jobs: 0,
            last_completed_at: None,
            last_error: None,
        }
    }

    #[test]
    fn event_bridge_uses_fast_polling_while_warming() {
        let mut health = ready_health();
        health.core_search_ready = false;
        assert_eq!(event_bridge_interval(None, Some(&health)), Duration::from_millis(500));
    }

    #[test]
    fn event_bridge_uses_indexing_interval_while_busy() {
        assert_eq!(
            event_bridge_interval(Some(&indexing_status("indexing")), Some(&ready_health())),
            Duration::from_secs(2),
        );
    }

    #[test]
    fn event_bridge_uses_idle_interval_when_ready() {
        assert_eq!(
            event_bridge_interval(Some(&indexing_status("idle")), Some(&ready_health())),
            Duration::from_secs(15),
        );
    }
}

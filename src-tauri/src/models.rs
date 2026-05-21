use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IndexedFolder {
    pub id: i64,
    pub path: String,
    pub display_name: String,
    pub is_active: bool,
    pub item_count: i64,
    pub image_count: i64,
    pub document_count: i64,
    pub voice_note_count: i64,
    pub last_indexed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FolderSelectionResult {
    pub added_folders: Vec<IndexedFolder>,
    pub skipped_paths: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchRequest {
    pub query: String,
    pub scope: String,
    pub folder_ids: Option<Vec<i64>>,
    pub sort: String,
    pub limit: u32,
    pub offset: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchResult {
    pub asset_id: i64,
    pub asset_type: String,
    pub path: String,
    pub filename: String,
    pub thumbnail_path: Option<String>,
    pub preview_path: Option<String>,
    pub modified_at: String,
    pub created_at: Option<String>,
    pub ocr_snippet: Option<String>,
    pub snippet: Option<String>,
    pub semantic_score: f32,
    pub text_score: f32,
    pub final_score: f32,
    pub folder_id: i64,
    pub folder_name: Option<String>,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub page_number: Option<i64>,
    pub start_ms: Option<i64>,
    pub end_ms: Option<i64>,
    pub duration_ms: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchResponse {
    pub results: Vec<SearchResult>,
    pub took_ms: u64,
    pub total_hits: u64,
    pub query_debug: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IndexingStatus {
    pub state: String,
    pub active_job_id: Option<i64>,
    pub active_job_type: Option<String>,
    pub items_total: u64,
    pub items_processed: u64,
    pub queued_jobs: u64,
    pub last_completed_at: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartupMetrics {
    pub core_search_ready_ms: Option<u64>,
    pub embedding_init_ms: Option<u64>,
    pub vector_bootstrap_ms: Option<u64>,
    pub ocr_init_ms: Option<u64>,
    pub vector_bootstrap_mode: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppHealth {
    pub worker_ready: bool,
    pub database_ready: bool,
    pub text_search_ready: bool,
    pub semantic_search_ready: bool,
    pub image_semantic_ready: bool,
    pub text_semantic_ready: bool,
    pub image_vector_ready: bool,
    pub text_vector_ready: bool,
    pub image_scope_ready: bool,
    pub document_scope_ready: bool,
    pub voice_note_scope_ready: bool,
    pub core_search_ready: bool,
    pub core_search_phase: String,
    pub core_search_message: String,
    pub indexing_phase: String,
    pub indexing_message: String,
    pub vector_engine: String,
    pub ocr_engine: String,
    pub embedding_engine: String,
    pub degraded: bool,
    pub message: String,
    pub startup_metrics: Option<StartupMetrics>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerRequest {
    pub id: u64,
    pub method: String,
    pub params: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerResponse {
    pub id: u64,
    pub result: Option<Value>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FsEventPayload {
    pub kind: String,
    pub path: String,
}

use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use arboard::Clipboard;
use rfd::FileDialog;
use serde_json::json;
use tauri::{AppHandle, State};

use crate::{
    models::{
        AppHealth, FolderSelectionResult, IndexedFolder, IndexingStatus, SearchRequest,
        SearchResponse,
    },
    state::AppState,
};

#[tauri::command]
pub async fn select_folders(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<FolderSelectionResult, String> {
    let Some(paths) = FileDialog::new()
        .set_title("Select folders to index in Recall")
        .pick_folders()
    else {
        return Ok(FolderSelectionResult {
            added_folders: Vec::new(),
            skipped_paths: Vec::new(),
        });
    };

    let payload = json!({
      "paths": paths
        .into_iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect::<Vec<_>>()
    });

    let worker = state.worker.client().await?;
    let result: FolderSelectionResult = worker.request("add_folders", payload).await?;
    state.sync_watched_folders().await?;
    state.emit_current_snapshots(&app).await?;
    Ok(result)
}

#[tauri::command]
pub async fn list_indexed_folders(
    state: State<'_, AppState>,
) -> Result<Vec<IndexedFolder>, String> {
    state.list_indexed_folders()
}

#[tauri::command]
pub async fn remove_indexed_folder(
    folder_id: i64,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let worker = state.worker.client().await?;
    let _: serde_json::Value = worker
        .request("remove_folder", json!({ "folderId": folder_id }))
        .await?;
    state.sync_watched_folders().await?;
    state.emit_current_snapshots(&app).await?;
    Ok(())
}

#[tauri::command]
pub async fn get_indexing_status(state: State<'_, AppState>) -> Result<IndexingStatus, String> {
    state.read_indexing_status()
}

#[tauri::command]
pub async fn search_images(
    request: SearchRequest,
    state: State<'_, AppState>,
) -> Result<SearchResponse, String> {
    if request.query.trim().is_empty() {
        return state.search_recent_images(&request);
    }

    let worker = state.worker.client().await?;
    worker
        .request("search", json!({ "request": request }))
        .await
}

#[tauri::command]
pub async fn open_file_location(path: String) -> Result<(), String> {
    let canonical = canonicalize_path(&path)?;
    Command::new("explorer")
        .arg(format!("/select,{}", canonical.display()))
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn copy_image_path(path: String) -> Result<(), String> {
    let canonical = canonicalize_path(&path)?;
    let mut clipboard = Clipboard::new().map_err(|error| error.to_string())?;
    clipboard
        .set_text(canonical.to_string_lossy().to_string())
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn get_app_health(state: State<'_, AppState>) -> Result<AppHealth, String> {
    state.get_app_health().await
}

fn canonicalize_path(path: &str) -> Result<PathBuf, String> {
    let target = Path::new(path);
    if !target.exists() {
        return Err(format!("Path does not exist: {}", target.display()));
    }

    fs::canonicalize(target).map_err(|error| error.to_string())
}

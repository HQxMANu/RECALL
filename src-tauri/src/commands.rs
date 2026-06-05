use std::process::Command;

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
pub async fn rebuild_index(
    folder_ids: Option<Vec<i64>>,
    force: Option<bool>,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let worker = state.worker.client().await?;
    let _: serde_json::Value = worker
        .request(
            "rebuild_index",
            json!({
                "folderIds": folder_ids.unwrap_or_default(),
                "force": force.unwrap_or(false),
            }),
        )
        .await?;
    state.emit_current_snapshots(&app).await?;
    Ok(())
}

#[tauri::command]
pub async fn get_indexing_status(state: State<'_, AppState>) -> Result<IndexingStatus, String> {
    state.read_indexing_status()
}

#[tauri::command]
pub async fn search_assets(
    request: SearchRequest,
    state: State<'_, AppState>,
) -> Result<SearchResponse, String> {
    if request.query.trim().is_empty() {
        return state.search_recent_assets(&request);
    }

    let worker = state.worker.client().await?;
    worker
        .request("search_assets", json!({ "request": request }))
        .await
}

#[tauri::command]
pub async fn search_images(
    request: SearchRequest,
    state: State<'_, AppState>,
) -> Result<SearchResponse, String> {
    search_assets(request, state).await
}

#[tauri::command]
pub async fn resolve_asset_preview_source(
    asset_id: i64,
    variant: String,
    state: State<'_, AppState>,
) -> Result<Option<String>, String> {
    state.resolve_asset_preview_source(asset_id, &variant)
}

#[tauri::command]
pub async fn open_file_location(asset_id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let canonical = state.resolve_asset_path(asset_id)?;
    Command::new("explorer.exe")
        .arg("/select,")
        .arg(&canonical)
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn copy_asset_path(asset_id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let canonical = state.resolve_asset_path(asset_id)?;
    let mut clipboard = Clipboard::new().map_err(|error| error.to_string())?;
    clipboard
        .set_text(canonical.to_string_lossy().to_string())
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn copy_image_path(asset_id: i64, state: State<'_, AppState>) -> Result<(), String> {
    copy_asset_path(asset_id, state).await
}

#[tauri::command]
pub async fn open_asset_file(asset_id: i64, state: State<'_, AppState>) -> Result<(), String> {
    let canonical = state.resolve_asset_path(asset_id)?;
    opener::open(&canonical).map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn get_app_health(state: State<'_, AppState>) -> Result<AppHealth, String> {
    state.get_app_health().await
}

use std::{
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{anyhow, Context};
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use rusqlite::{params, params_from_iter, types::Value, Connection, OptionalExtension};
use serde_json::json;

use crate::models::{
    AssetIssue, IndexedFolder, IndexingStatus, SearchRequest, SearchResponse, SearchResult,
};

#[derive(Debug)]
struct AssetRecord {
    path: String,
    asset_type: String,
    preview_path: Option<String>,
}

fn open_database(app_data_dir: &Path) -> anyhow::Result<Option<Connection>> {
    let database_path = app_data_dir.join("recall.db");
    if !database_path.exists() {
        return Ok(None);
    }

    let connection = Connection::open(&database_path)
        .with_context(|| format!("Failed to open {}", database_path.display()))?;
    Ok(Some(connection))
}

pub fn list_indexed_folders(app_data_dir: &Path) -> anyhow::Result<Vec<IndexedFolder>> {
    let Some(connection) = open_database(app_data_dir)? else {
        return Ok(Vec::new());
    };

    let mut statement = connection.prepare(
        r#"
    SELECT f.id, f.path, f.display_name, f.is_active,
           COUNT(a.id) AS item_count,
           SUM(CASE WHEN a.asset_type = 'image' THEN 1 ELSE 0 END) AS image_count,
           SUM(CASE WHEN a.asset_type = 'document' THEN 1 ELSE 0 END) AS document_count,
           SUM(CASE WHEN a.asset_type = 'voice-note' THEN 1 ELSE 0 END) AS voice_note_count,
           MAX(a.last_indexed_at) AS last_indexed_at
    FROM indexed_folders f
    LEFT JOIN indexed_assets a ON a.folder_id = f.id
    WHERE f.is_active = 1
    GROUP BY f.id
    ORDER BY f.display_name COLLATE NOCASE
    "#,
    )?;

    let rows = statement.query_map([], |row| {
        Ok(IndexedFolder {
            id: row.get("id")?,
            path: row.get("path")?,
            display_name: row.get("display_name")?,
            is_active: row.get("is_active")?,
            item_count: row.get("item_count")?,
            image_count: row.get("image_count")?,
            document_count: row.get("document_count")?,
            voice_note_count: row.get("voice_note_count")?,
            last_indexed_at: row.get("last_indexed_at")?,
        })
    })?;

    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

pub fn read_indexing_status(app_data_dir: &Path) -> anyhow::Result<IndexingStatus> {
    let Some(connection) = open_database(app_data_dir)? else {
        return Ok(idle_status());
    };

    let mut statement = connection.prepare(
        r#"
    SELECT id, job_type, status, items_total, items_processed, finished_at, error_message
    FROM indexing_jobs
    ORDER BY
      CASE status
        WHEN 'running' THEN 0
        ELSE 1
      END,
      COALESCE(finished_at, started_at) DESC
    LIMIT 1
    "#,
    )?;

    let recent_issues = recent_asset_issues(&connection)?;
    let issue_count = asset_issue_count(&connection)?;

    let Some(row) = statement
        .query_row([], |row| {
            Ok((
                row.get::<_, i64>("id")?,
                row.get::<_, String>("job_type")?,
                row.get::<_, String>("status")?,
                row.get::<_, i64>("items_total")?,
                row.get::<_, i64>("items_processed")?,
                row.get::<_, Option<String>>("finished_at")?,
                row.get::<_, Option<String>>("error_message")?,
            ))
        })
        .optional()?
    else {
        let mut status = idle_status();
        status.issue_count = issue_count;
        status.recent_issues = recent_issues;
        return Ok(status);
    };

    let state = match row.2.as_str() {
        "running" => "indexing",
        "failed" => "error",
        _ => "idle",
    };

    Ok(IndexingStatus {
        state: state.to_string(),
        active_job_id: (state == "indexing").then_some(row.0),
        active_job_type: (state == "indexing").then_some(row.1),
        items_total: row.3.max(0) as u64,
        items_processed: row.4.max(0) as u64,
        queued_jobs: 0,
        last_completed_at: row.5,
        last_error: row.6,
        issue_count,
        recent_issues,
    })
}

pub fn search_recent_assets(
    app_data_dir: &Path,
    request: &SearchRequest,
) -> anyhow::Result<SearchResponse> {
    let started = Instant::now();
    let Some(connection) = open_database(app_data_dir)? else {
        return Ok(SearchResponse {
            results: Vec::new(),
            took_ms: 0,
            total_hits: 0,
            query_debug: json!({
              "mode": "browse",
              "semanticCandidates": 0,
              "textCandidates": 0
            }),
        });
    };

    let folder_ids = request.folder_ids.clone().unwrap_or_default();
    let order = if request.sort == "oldest" {
        "ASC"
    } else {
        "DESC"
    };
    let mut sql = format!(
        r#"
    SELECT a.id, a.asset_type, a.path, a.filename, a.preview_path, a.modified_at_fs, a.created_at_fs,
           a.folder_id, f.display_name AS folder_name, a.width, a.height, a.duration_ms
    FROM indexed_assets a
    JOIN indexed_folders f ON f.id = a.folder_id
    WHERE a.asset_type = ?
    "#
    );

    let asset_type = match request.scope.as_str() {
        "documents" => "document",
        "voice-notes" => "voice-note",
        _ => "image",
    };

    let mut params: Vec<Value> = vec![Value::from(asset_type.to_string())];
    if !folder_ids.is_empty() {
        let placeholders = vec!["?"; folder_ids.len()].join(",");
        sql.push_str(&format!(" AND a.folder_id IN ({placeholders})"));
        params.extend(folder_ids.into_iter().map(Value::from));
    }

    sql.push_str(&format!(
        " ORDER BY a.modified_at_fs {order} LIMIT ? OFFSET ?"
    ));
    params.push(Value::from(i64::from(request.limit)));
    params.push(Value::from(i64::from(request.offset)));

    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map(params_from_iter(params), |row| {
        Ok(SearchResult {
            asset_id: row.get("id")?,
            asset_type: row.get("asset_type")?,
            path: row.get("path")?,
            filename: row.get("filename")?,
            thumbnail_path: row.get("preview_path")?,
            preview_path: row.get("preview_path")?,
            modified_at: row.get("modified_at_fs")?,
            created_at: row.get("created_at_fs")?,
            ocr_snippet: None,
            snippet: None,
            semantic_score: 0.0,
            text_score: 0.0,
            final_score: 0.0,
            folder_id: row.get("folder_id")?,
            folder_name: row.get("folder_name")?,
            width: row.get("width")?,
            height: row.get("height")?,
            page_number: None,
            start_ms: None,
            end_ms: None,
            duration_ms: row.get("duration_ms")?,
        })
    })?;

    let results = rows.collect::<Result<Vec<_>, _>>()?;
    Ok(SearchResponse {
        total_hits: results.len() as u64,
        took_ms: started.elapsed().as_millis() as u64,
        results,
        query_debug: json!({
          "mode": "browse",
          "semanticCandidates": 0,
          "textCandidates": 0
        }),
    })
}

pub fn resolve_asset_path(app_data_dir: &Path, asset_id: i64) -> anyhow::Result<PathBuf> {
    let asset = load_asset_record(app_data_dir, asset_id)?;
    canonicalize_existing_path(&asset.path)
}

pub fn resolve_asset_preview_source(
    app_data_dir: &Path,
    asset_id: i64,
    variant: &str,
) -> anyhow::Result<Option<String>> {
    let asset = load_asset_record(app_data_dir, asset_id)?;
    let preview_candidate = asset
        .preview_path
        .as_deref()
        .filter(|path| !path.trim().is_empty())
        .map(canonicalize_existing_path)
        .transpose()?;

    let asset_path = canonicalize_existing_path(&asset.path)?;
    let selected_path = match variant {
        "thumbnail" => preview_candidate
            .or_else(|| (asset.asset_type == "image").then_some(asset_path.clone())),
        "preview" => {
            if asset.asset_type == "image" {
                Some(asset_path.clone())
            } else {
                preview_candidate
            }
        }
        other => return Err(anyhow!("Unsupported preview variant: {other}")),
    };

    selected_path
        .map(read_data_url)
        .transpose()
        .with_context(|| format!("Failed to prepare {variant} preview for asset {asset_id}"))
}

fn recent_asset_issues(connection: &Connection) -> anyhow::Result<Vec<AssetIssue>> {
    let mut statement = connection.prepare(
        r#"
    SELECT a.id, a.asset_type, a.filename, a.path, a.folder_id, f.display_name AS folder_name,
           COALESCE(a.error_message, 'Indexing failed without a detailed error message.') AS error_message,
           a.last_indexed_at
    FROM indexed_assets a
    JOIN indexed_folders f ON f.id = a.folder_id
    WHERE a.index_status = 'error' OR (a.error_message IS NOT NULL AND a.error_message != '')
    ORDER BY COALESCE(a.last_indexed_at, a.modified_at_fs) DESC, a.id DESC
    LIMIT 5
    "#,
    )?;

    let rows = statement.query_map([], |row| {
        Ok(AssetIssue {
            asset_id: row.get("id")?,
            asset_type: row.get("asset_type")?,
            filename: row.get("filename")?,
            path: row.get("path")?,
            folder_id: row.get("folder_id")?,
            folder_name: row.get("folder_name")?,
            error_message: row.get("error_message")?,
            last_indexed_at: row.get("last_indexed_at")?,
        })
    })?;

    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn asset_issue_count(connection: &Connection) -> anyhow::Result<u64> {
    let count = connection.query_row(
        r#"
        SELECT COUNT(*)
        FROM indexed_assets
        WHERE index_status = 'error' OR (error_message IS NOT NULL AND error_message != '')
        "#,
        [],
        |row| row.get::<_, i64>(0),
    )?;

    Ok(count.max(0) as u64)
}

fn load_asset_record(app_data_dir: &Path, asset_id: i64) -> anyhow::Result<AssetRecord> {
    let Some(connection) = open_database(app_data_dir)? else {
        return Err(anyhow!(
            "Recall has not created its local database yet, so asset {asset_id} is unavailable."
        ));
    };

    connection
        .query_row(
            r#"
            SELECT path, asset_type, preview_path
            FROM indexed_assets
            WHERE id = ?
            "#,
            params![asset_id],
            |row| {
                Ok(AssetRecord {
                    path: row.get("path")?,
                    asset_type: row.get("asset_type")?,
                    preview_path: row.get("preview_path")?,
                })
            },
        )
        .optional()?
        .ok_or_else(|| anyhow!("Could not find asset {asset_id} in the local index."))
}

fn canonicalize_existing_path(path: &str) -> anyhow::Result<PathBuf> {
    let candidate = Path::new(path);
    if !candidate.exists() {
        return Err(anyhow!("Path does not exist: {}", candidate.display()));
    }

    fs::canonicalize(candidate)
        .with_context(|| format!("Failed to resolve {}", candidate.display()))
}

fn read_data_url(path: PathBuf) -> anyhow::Result<String> {
    let bytes = fs::read(&path).with_context(|| format!("Failed to read {}", path.display()))?;
    let mime_type = guess_mime_type(&path);
    Ok(format!(
        "data:{mime_type};base64,{}",
        BASE64_STANDARD.encode(bytes)
    ))
}

fn guess_mime_type(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_ascii_lowercase())
        .as_deref()
    {
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("webp") => "image/webp",
        Some("gif") => "image/gif",
        Some("bmp") => "image/bmp",
        Some("svg") => "image/svg+xml",
        _ => "application/octet-stream",
    }
}

fn idle_status() -> IndexingStatus {
    IndexingStatus {
        state: "idle".to_string(),
        active_job_id: None,
        active_job_type: None,
        items_total: 0,
        items_processed: 0,
        queued_jobs: 0,
        last_completed_at: None,
        last_error: None,
        issue_count: 0,
        recent_issues: Vec::new(),
    }
}

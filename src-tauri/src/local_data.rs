use std::{path::Path, time::Instant};

use anyhow::Context;
use rusqlite::{params_from_iter, types::Value, Connection, OptionalExtension};
use serde_json::json;

use crate::models::{IndexedFolder, IndexingStatus, SearchRequest, SearchResponse, SearchResult};

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
           COUNT(i.id) AS image_count,
           MAX(i.last_indexed_at) AS last_indexed_at
    FROM indexed_folders f
    LEFT JOIN indexed_images i ON i.folder_id = f.id
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
            image_count: row.get("image_count")?,
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
        WHEN 'failed' THEN 1
        ELSE 2
      END,
      COALESCE(finished_at, started_at) DESC
    LIMIT 1
    "#,
    )?;

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
        return Ok(idle_status());
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
    })
}

pub fn search_recent_images(
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
    SELECT i.id, i.path, i.filename, i.thumbnail_path, i.modified_at_fs, i.created_at_fs,
           i.ocr_text, i.folder_id, f.display_name AS folder_name, i.width, i.height
    FROM indexed_images i
    JOIN indexed_folders f ON f.id = i.folder_id
    WHERE 1 = 1
    "#
    );

    let mut params: Vec<Value> = Vec::new();
    if !folder_ids.is_empty() {
        let placeholders = vec!["?"; folder_ids.len()].join(",");
        sql.push_str(&format!(" AND i.folder_id IN ({placeholders})"));
        params.extend(folder_ids.into_iter().map(Value::from));
    }

    sql.push_str(&format!(
        " ORDER BY i.modified_at_fs {order} LIMIT ? OFFSET ?"
    ));
    params.push(Value::from(i64::from(request.limit)));
    params.push(Value::from(i64::from(request.offset)));

    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map(params_from_iter(params), |row| {
        Ok(SearchResult {
            image_id: row.get("id")?,
            path: row.get("path")?,
            filename: row.get("filename")?,
            thumbnail_path: row.get("thumbnail_path")?,
            modified_at: row.get("modified_at_fs")?,
            created_at: row.get("created_at_fs")?,
            ocr_snippet: row
                .get::<_, Option<String>>("ocr_text")?
                .map(|value| value.chars().take(280).collect()),
            semantic_score: 0.0,
            text_score: 0.0,
            final_score: 0.0,
            folder_id: row.get("folder_id")?,
            folder_name: row.get("folder_name")?,
            width: row.get("width")?,
            height: row.get("height")?,
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
    }
}

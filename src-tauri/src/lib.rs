mod commands;
mod local_data;
mod models;
mod process;
mod state;
mod watchers;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            let state = state::AppState::new(&app.handle())
                .map_err(|error| std::io::Error::other(error.to_string()))?;

            let sync_state = state.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(error) = sync_state.sync_watched_folders().await {
                    log::warn!("Failed to initialize folder watchers: {error}");
                }
            });

            state.prewarm_worker();
            state.start_event_bridge(app.handle().clone());
            app.manage(state);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("Recall");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::select_folders,
            commands::list_indexed_folders,
            commands::remove_indexed_folder,
            commands::get_indexing_status,
            commands::search_images,
            commands::open_file_location,
            commands::copy_image_path,
            commands::get_app_health,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

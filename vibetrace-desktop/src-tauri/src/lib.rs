//! VibeTrace Desktop - Library entry
//!
//! 提供 Tauri commands 给前端 (React/Svelte) 调用, 启动嵌入式 HTTP API.

pub mod analyst;
pub mod commands;
pub mod events;
pub mod http_api;
pub mod store;
pub mod tracer;

use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

/// App state - shared between Tauri commands and HTTP server
pub struct AppState {
    pub tracer: Arc<tracer::Tracer>,
    pub store: Arc<store::Store>,
    pub http_handle: Mutex<Option<tokio::task::JoinHandle<()>>>,
    pub http_port: Mutex<u16>,
}

impl AppState {
    pub fn new(db_path: &std::path::Path) -> anyhow::Result<Self> {
        let store = Arc::new(store::Store::open(db_path)?);
        let tracer = Arc::new(tracer::Tracer::new(store.clone(), 3));
        Ok(Self {
            tracer,
            store,
            http_handle: Mutex::new(None),
            http_port: Mutex::new(0),
        })
    }
}

/// Tauri app entrypoint
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"))
        )
        .init();

    tauri::Builder::default()
        .setup(|app| {
            // Get app data dir
            let app_data = app.path().app_data_dir()
                .expect("Failed to get app data dir");
            std::fs::create_dir_all(&app_data).ok();
            let db_path = app_data.join("vibetrace.db");
            tracing::info!("Database at: {}", db_path.display());

            let state = AppState::new(&db_path).expect("Failed to init store");
            app.manage(state);

            // Auto-start HTTP server on port 7842
            let state: tauri::State<AppState> = app.state();
            let tracer = state.tracer.clone();
            let port: u16 = 7842;
            let addr: std::net::SocketAddr = format!("127.0.0.1:{}", port).parse().unwrap();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = http_api::start_server(addr, tracer).await {
                    tracing::error!("HTTP server error: {}", e);
                }
            });
            *state.http_port.blocking_lock() = port;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_traces,
            commands::get_trace,
            commands::get_events,
            commands::get_stats,
            commands::analyze_trace,
            commands::start_trace,
            commands::end_trace,
            commands::record_event,
            commands::delete_trace,
            commands::init_claude_code_hooks,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

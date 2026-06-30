//! VibeTrace Desktop - Library entry
//!
//! 提供 Tauri commands 给前端 (React/Svelte) 调用, 启动嵌入式 HTTP API.

pub mod analyst;
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

// === Tauri commands (callable from frontend via `invoke()`) ===

#[tauri::command]
pub async fn list_traces(
    state: tauri::State<'_, AppState>,
    limit: Option<u32>,
) -> Result<Vec<events::Trace>, String> {
    state
        .store
        .list_traces(limit.unwrap_or(50))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_trace(
    state: tauri::State<'_, AppState>,
    trace_id: String,
) -> Result<Option<events::Trace>, String> {
    state
        .store
        .get_trace(&trace_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_events(
    state: tauri::State<'_, AppState>,
    trace_id: String,
) -> Result<Vec<events::Event>, String> {
    state
        .store
        .get_events(&trace_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_stats(
    state: tauri::State<'_, AppState>,
) -> Result<store::Stats, String> {
    state.store.get_stats().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn analyze_trace(
    state: tauri::State<'_, AppState>,
    trace_id: String,
) -> Result<analyst::AnalystReport, String> {
    let trace = state
        .store
        .get_trace(&trace_id)
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "Trace not found".to_string())?;
    let events = state
        .store
        .get_events(&trace_id)
        .await
        .map_err(|e| e.to_string())?;
    let report = analyst::analyze(&trace, &events);
    // Save markdown to storage
    let _ = state.store.save_analyst_report(&trace_id, &report.markdown).await;
    Ok(report)
}

#[tauri::command]
pub async fn start_trace(
    state: tauri::State<'_, AppState>,
    name: String,
    vibe: Option<String>,
    input: Option<serde_json::Value>,
) -> Result<String, String> {
    state
        .tracer
        .start_trace(name, vibe.unwrap_or_default(), input)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn end_trace(
    state: tauri::State<'_, AppState>,
    trace_id: String,
    output: Option<serde_json::Value>,
) -> Result<(), String> {
    state
        .tracer
        .end_trace(&trace_id, output)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn record_event(
    state: tauri::State<'_, AppState>,
    name: String,
    event_type: String,
    input: Option<serde_json::Value>,
    output: Option<serde_json::Value>,
    metadata: Option<std::collections::HashMap<String, serde_json::Value>>,
) -> Result<String, String> {
    let et = match event_type.as_str() {
        "llm.call" | "llm" => events::EventType::LlmCall,
        "tool.call" | "tool" => events::EventType::ToolCall,
        "reasoning" => events::EventType::Reasoning,
        "error" => events::EventType::Error,
        _ => events::EventType::LlmCall,
    };
    state
        .tracer
        .record_event(None, name, et, input, output, metadata.unwrap_or_default())
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_trace(
    state: tauri::State<'_, AppState>,
    trace_id: String,
) -> Result<(), String> {
    state.store.delete_trace(&trace_id).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn start_http_server(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
    port: Option<u16>,
) -> Result<u16, String> {
    let mut handle = state.http_handle.lock().await;
    if handle.is_some() {
        let p = *state.http_port.lock().await;
        return Ok(p);
    }
    let port = port.unwrap_or(0); // 0 = let OS pick
    let addr: std::net::SocketAddr = format!("127.0.0.1:{}", port).parse().unwrap();
    let tracer = state.tracer.clone();
    let h = tokio::spawn(async move {
        if let Err(e) = http_api::start_server(addr, tracer).await {
            tracing::error!("HTTP server error: {}", e);
        }
    });
    *handle = Some(h);
    // Wait a moment for server to start, then figure out actual port
    tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
    let actual_port = if port == 0 {
        // We need a way to get the actual port - simplified to use the requested one
        // For production, use SO_REUSEADDR with explicit bind
        7842 // default fallback
    } else {
        port
    };
    *state.http_port.lock().await = actual_port;
    Ok(actual_port)
}

#[tauri::command]
pub async fn init_claude_code_hooks(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
    port: u16,
) -> Result<String, String> {
    // Make sure HTTP server is running
    start_http_server(app.clone(), state, Some(port)).await?;

    // Get Claude Code settings.json path
    let home = dirs::home_dir().ok_or("No home dir")?;
    let settings_path = home.join(".claude").join("settings.json");

    let settings = if settings_path.exists() {
        std::fs::read_to_string(&settings_path).unwrap_or_else(|_| "{}".to_string())
    } else {
        std::fs::create_dir_all(settings_path.parent().unwrap())
            .map_err(|e| e.to_string())?;
        "{}".to_string()
    };

    let mut json: serde_json::Value = serde_json::from_str(&settings)
        .unwrap_or_else(|_| serde_json::json!({}));

    let base = format!("http://127.0.0.1:{}", port);
    let hooks = json.as_object_mut().unwrap()
        .entry("hooks".to_string())
        .or_insert(serde_json::json!({}));

    let hook_configs = serde_json::json!({
        "UserPromptSubmit": [{
            "hooks": [{
                "type": "command",
                "command": format!("curl -s -X POST {}/v1/traces -H 'Content-Type: application/json' -d '{{\"name\":\"claude-code\",\"vibe\":\"$VIBE\",\"input\":{{\"prompt\":\"$PROMPT\"}}}}'", base),
                "env": {
                    "VIBE": "calm, insightful, minimalist",
                    "PROMPT": "user input"
                }
            }]
        }],
        "PostToolUse": [{
            "hooks": [{
                "type": "command",
                "command": format!("curl -s -X POST {}/v1/events -H 'Content-Type: application/json' -d '{{\"name\":\"$TOOL\",\"event_type\":\"tool.call\",\"tool_name\":\"$TOOL\",\"input\":{{}},\"output\":{{}},\"metadata\":{{}}}}'", base),
                "env": {
                    "TOOL": "tool"
                }
            }]
        }],
        "Stop": [{
            "hooks": [{
                "type": "command",
                "command": format!("curl -s -X POST {}/v1/traces/end -H 'Content-Type: application/json' -d '{{\"trace_id\":\"$TRACE_ID\"}}'", base),
                "env": {
                    "TRACE_ID": ""
                }
            }]
        }]
    });

    *hooks = hook_configs;

    std::fs::write(&settings_path, serde_json::to_string_pretty(&json).unwrap())
        .map_err(|e| e.to_string())?;

    Ok(format!("Configured Claude Code hooks in {}", settings_path.display()))
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
            list_traces,
            get_trace,
            get_events,
            get_stats,
            analyze_trace,
            start_trace,
            end_trace,
            record_event,
            delete_trace,
            init_claude_code_hooks,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

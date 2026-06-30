//! Tauri commands - 移到独立模块以避免 #[tauri::command] 宏重复定义
//!
//! 根因: tauri 2.0+ 的 `#[tauri::command]` 宏把 `__cmd__xxx` macro_rules 定义在
//! 函数所在的 module 命名空间。当 `tauri::generate_handler!` 引用 `cmd1` 时,
//! 它通过 `self::__cmd__cmd1` 查找, 在 lib.rs 顶层重复定义会冲突.
//!
//! 修复: 把所有 commands 放到独立子模块, 让 macro 在子模块内 scope 限定.

use crate::AppState;
use tauri::State;

#[tauri::command]
pub async fn list_traces(
    state: State<'_, AppState>,
    limit: Option<u32>,
) -> Result<Vec<crate::events::Trace>, String> {
    state
        .store
        .list_traces(limit.unwrap_or(50))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_trace(
    state: State<'_, AppState>,
    trace_id: String,
) -> Result<Option<crate::events::Trace>, String> {
    state
        .store
        .get_trace(&trace_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_events(
    state: State<'_, AppState>,
    trace_id: String,
) -> Result<Vec<crate::events::Event>, String> {
    state
        .store
        .get_events(&trace_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_stats(state: State<'_, AppState>) -> Result<crate::store::Stats, String> {
    state.store.get_stats().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn analyze_trace(
    state: State<'_, AppState>,
    trace_id: String,
) -> Result<crate::analyst::AnalystReport, String> {
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
    let report = crate::analyst::analyze(&trace, &events);
    let _ = state
        .store
        .save_analyst_report(&trace_id, &report.markdown)
        .await;
    Ok(report)
}

#[tauri::command]
pub async fn start_trace(
    state: State<'_, AppState>,
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
    state: State<'_, AppState>,
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
    state: State<'_, AppState>,
    name: String,
    event_type: String,
    input: Option<serde_json::Value>,
    output: Option<serde_json::Value>,
    metadata: Option<std::collections::HashMap<String, serde_json::Value>>,
) -> Result<String, String> {
    let et = match event_type.as_str() {
        "llm.call" | "llm" => crate::events::EventType::LlmCall,
        "tool.call" | "tool" => crate::events::EventType::ToolCall,
        "reasoning" => crate::events::EventType::Reasoning,
        "error" => crate::events::EventType::Error,
        _ => crate::events::EventType::LlmCall,
    };
    state
        .tracer
        .record_event(None, name, et, input, output, metadata.unwrap_or_default())
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_trace(state: State<'_, AppState>, trace_id: String) -> Result<(), String> {
    state
        .store
        .delete_trace(&trace_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn init_claude_code_hooks(
    state: State<'_, AppState>,
    port: u16,
) -> Result<String, String> {
    // Make sure HTTP server is running
    {
        let mut handle = state.http_handle.lock().await;
        if handle.is_none() {
            let addr: std::net::SocketAddr = format!("127.0.0.1:{}", port).parse().unwrap();
            let tracer = state.tracer.clone();
            let h = tokio::spawn(async move {
                if let Err(e) = crate::http_api::start_server(addr, tracer).await {
                    tracing::error!("HTTP server error: {}", e);
                }
            });
            *handle = Some(h);
            tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
            *state.http_port.lock().await = port;
        }
    }

    // Get Claude Code settings.json path
    let home = dirs::home_dir().ok_or("No home dir")?;
    let settings_path = home.join(".claude").join("settings.json");

    let settings = if settings_path.exists() {
        std::fs::read_to_string(&settings_path).unwrap_or_else(|_| "{}".to_string())
    } else {
        std::fs::create_dir_all(settings_path.parent().unwrap()).map_err(|e| e.to_string())?;
        "{}".to_string()
    };

    let mut json: serde_json::Value =
        serde_json::from_str(&settings).unwrap_or_else(|_| serde_json::json!({}));

    let base = format!("http://127.0.0.1:{}", port);
    let hooks = json
        .as_object_mut()
        .unwrap()
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

    Ok(format!(
        "Configured Claude Code hooks in {}",
        settings_path.display()
    ))
}

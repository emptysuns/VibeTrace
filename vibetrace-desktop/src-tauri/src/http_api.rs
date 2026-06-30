//! VibeTrace - HTTP API (给 Claude Code hooks 调用)
//!
//! 启动一个轻量 HTTP server, 监听 127.0.0.1:<port>.
//! Claude Code 通过 settings.json hooks 配置, 每次 user prompt / tool use
//! 都会 curl 这个 server, 自动记录到本地 SQLite.

use crate::events::EventType;
use crate::tracer::Tracer;
use axum::{
    extract::{Json, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::cors::CorsLayer;

#[derive(Clone)]
pub struct ApiState {
    pub tracer: Arc<Tracer>,
}

#[derive(Debug, Deserialize)]
pub struct TraceStartReq {
    pub name: String,
    #[serde(default)]
    pub vibe: String,
    #[serde(default)]
    pub input: Option<serde_json::Value>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Serialize)]
pub struct TraceStartResp {
    pub trace_id: String,
}

#[derive(Debug, Deserialize)]
pub struct TraceEndReq {
    pub trace_id: String,
    #[serde(default)]
    pub output: Option<serde_json::Value>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct EventReq {
    pub trace_id: Option<String>,
    pub name: String,
    pub event_type: String,
    #[serde(default)]
    pub input: Option<serde_json::Value>,
    #[serde(default)]
    pub output: Option<serde_json::Value>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    /// LLM specific
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub prompt_tokens: Option<u32>,
    #[serde(default)]
    pub completion_tokens: Option<u32>,
    #[serde(default)]
    pub tool_name: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct EventResp {
    pub event_id: String,
}

pub fn router(state: ApiState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/v1/traces", post(start_trace))
        .route("/v1/traces/end", post(end_trace))
        .route("/v1/events", post(record_event))
        .route("/v1/events/finish", post(finish_event))
        .layer(CorsLayer::permissive())
        .with_state(state)
}

async fn health() -> impl IntoResponse {
    Json(serde_json::json!({
        "status": "ok",
        "service": "vibetrace",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}

async fn start_trace(
    State(s): State<ApiState>,
    Json(req): Json<TraceStartReq>,
) -> Result<Json<TraceStartResp>, (StatusCode, String)> {
    s.tracer
        .start_trace(req.name, req.vibe, req.input)
        .await
        .map(|trace_id| Json(TraceStartResp { trace_id }))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn end_trace(
    State(s): State<ApiState>,
    Json(req): Json<TraceEndReq>,
) -> Result<StatusCode, (StatusCode, String)> {
    s.tracer
        .end_trace(&req.trace_id, req.output)
        .await
        .map(|_| StatusCode::OK)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn record_event(
    State(s): State<ApiState>,
    Json(req): Json<EventReq>,
) -> Result<Json<EventResp>, (StatusCode, String)> {
    let event_type = parse_event_type(&req.event_type);
    let mut metadata = req.metadata;
    if let Some(m) = req.model {
        metadata.insert("model".into(), serde_json::Value::String(m));
    }
    if let Some(p) = req.prompt_tokens {
        metadata.insert("prompt_tokens".into(), serde_json::json!(p));
    }
    if let Some(c) = req.completion_tokens {
        metadata.insert("completion_tokens".into(), serde_json::json!(c));
    }
    if let Some(t) = req.tool_name {
        metadata.insert("tool_name".into(), serde_json::Value::String(t));
    }

    s.tracer
        .record_event(
            req.trace_id.as_deref(),
            req.name,
            event_type,
            req.input,
            req.output,
            metadata,
        )
        .await
        .map(|event_id| Json(EventResp { event_id }))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn finish_event(
    State(s): State<ApiState>,
    Json(req): Json<serde_json::Value>,
) -> Result<StatusCode, (StatusCode, String)> {
    let event_id = req.get("event_id").and_then(|v| v.as_str()).unwrap_or("");
    let output = req.get("output").cloned();
    let error = req.get("error").and_then(|v| v.as_str()).map(String::from);
    s.tracer
        .finish_event(event_id, output, error)
        .await
        .map(|_| StatusCode::OK)
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

fn parse_event_type(s: &str) -> EventType {
    match s {
        "trace.start" => EventType::TraceStart,
        "trace.end" => EventType::TraceEnd,
        "llm.call" | "llm" => EventType::LlmCall,
        "tool.call" | "tool" => EventType::ToolCall,
        "reasoning" => EventType::Reasoning,
        "memory.read" => EventType::MemoryRead,
        "memory.write" => EventType::MemoryWrite,
        "decision" => EventType::Decision,
        "error" => EventType::Error,
        "retry" => EventType::Retry,
        "human.input" => EventType::HumanInput,
        _ => EventType::LlmCall,
    }
}

pub async fn start_server(addr: SocketAddr, tracer: Arc<Tracer>) -> anyhow::Result<()> {
    let state = ApiState { tracer };
    let app = router(state);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    tracing::info!("VibeTrace HTTP server listening on http://{}", addr);
    axum::serve(listener, app).await?;
    Ok(())
}

//! VibeTrace - 核心事件模型
//!
//! 镜像 Python 版本的 events.py, 用 Rust 的 type safety 重新实现.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// 事件类型 - 与 Python 版对齐
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    TraceStart,
    TraceEnd,
    LlmCall,
    ToolCall,
    Reasoning,
    MemoryRead,
    MemoryWrite,
    Decision,
    Error,
    Retry,
    HumanInput,
}

impl EventType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::TraceStart => "trace.start",
            Self::TraceEnd => "trace.end",
            Self::LlmCall => "llm.call",
            Self::ToolCall => "tool.call",
            Self::Reasoning => "reasoning",
            Self::MemoryRead => "memory.read",
            Self::MemoryWrite => "memory.write",
            Self::Decision => "decision",
            Self::Error => "error",
            Self::Retry => "retry",
            Self::HumanInput => "human.input",
        }
    }

    pub fn emoji(&self) -> &'static str {
        match self {
            Self::TraceStart => "▶️",
            Self::TraceEnd => "⏹️",
            Self::LlmCall => "🤖",
            Self::ToolCall => "🔧",
            Self::Reasoning => "💭",
            Self::MemoryRead => "📖",
            Self::MemoryWrite => "✏️",
            Self::Decision => "🔀",
            Self::Error => "❌",
            Self::Retry => "🔁",
            Self::HumanInput => "👤",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum EventStatus {
    #[default]
    Ok,
    Error,
    Timeout,
    Cancelled,
}

impl EventStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Ok => "ok",
            Self::Error => "error",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
        }
    }
}

/// 事件 - 不可变记录
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub event_id: String,
    pub trace_id: String,
    pub parent_id: Option<String>,
    pub span_id: String,
    pub event_type: EventType,
    pub name: String,
    pub status: EventStatus,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub duration_ms: Option<f64>,

    /// Input / Output - 任意 JSON
    pub input: Option<serde_json::Value>,
    pub output: Option<serde_json::Value>,
    pub error: Option<String>,

    /// LLM specific
    pub model: Option<String>,
    pub prompt_tokens: Option<u32>,
    pub completion_tokens: Option<u32>,
    pub total_tokens: Option<u32>,
    pub cost_usd: Option<f64>,

    /// Tool specific
    pub tool_name: Option<String>,

    /// Free-form metadata
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub tags: Vec<String>,
}

impl Event {
    pub fn new(
        event_type: EventType,
        name: impl Into<String>,
        trace_id: impl Into<String>,
    ) -> Self {
        Self {
            event_id: Uuid::new_v4().to_string()[..16].to_string(),
            trace_id: trace_id.into(),
            parent_id: None,
            span_id: Uuid::new_v4().to_string()[..16].to_string(),
            event_type,
            name: name.into(),
            status: EventStatus::Ok,
            start_time: Utc::now(),
            end_time: None,
            duration_ms: None,
            input: None,
            output: None,
            error: None,
            model: None,
            prompt_tokens: None,
            completion_tokens: None,
            total_tokens: None,
            cost_usd: None,
            tool_name: None,
            metadata: HashMap::new(),
            tags: Vec::new(),
        }
    }

    pub fn finish(&mut self, status: EventStatus) {
        self.end_time = Some(Utc::now());
        self.duration_ms =
            Some((self.end_time.unwrap() - self.start_time).num_milliseconds() as f64);
        // 关键: 不要覆盖已经设置的 ERROR 状态
        if !(self.status == EventStatus::Error && self.error.is_some()) {
            self.status = status;
        }
    }
}

/// Trace - 一次完整 agent 运行
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trace {
    pub trace_id: String,
    pub name: String,
    pub vibe: String,
    pub start_time: DateTime<Utc>,
    pub end_time: Option<DateTime<Utc>>,
    pub duration_ms: Option<f64>,

    pub input: Option<serde_json::Value>,
    pub output: Option<serde_json::Value>,

    pub status: EventStatus,
    pub error: Option<String>,

    // 统计 (finish 时计算)
    pub total_events: u32,
    pub total_llm_calls: u32,
    pub total_tool_calls: u32,
    pub total_tokens: u32,
    pub total_cost_usd: f64,
    pub error_count: u32,

    pub metadata: HashMap<String, serde_json::Value>,
    pub tags: Vec<String>,
}

impl Trace {
    pub fn new(name: impl Into<String>, vibe: impl Into<String>) -> Self {
        Self {
            trace_id: Uuid::new_v4().to_string()[..16].to_string(),
            name: name.into(),
            vibe: vibe.into(),
            start_time: Utc::now(),
            end_time: None,
            duration_ms: None,
            input: None,
            output: None,
            status: EventStatus::Ok,
            error: None,
            total_events: 0,
            total_llm_calls: 0,
            total_tool_calls: 0,
            total_tokens: 0,
            total_cost_usd: 0.0,
            error_count: 0,
            metadata: HashMap::new(),
            tags: Vec::new(),
        }
    }

    pub fn finish(&mut self, status: EventStatus) {
        self.end_time = Some(Utc::now());
        self.duration_ms =
            Some((self.end_time.unwrap() - self.start_time).num_milliseconds() as f64);
        self.status = status;
    }
}

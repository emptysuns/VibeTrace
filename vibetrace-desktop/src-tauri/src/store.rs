//! VibeTrace - SQLite 存储后端
//!
//! 与 Python 版的关键差异:
//! - 用 rusqlite (Rust 原生绑定),无外部依赖
//! - 使用 `bundled` feature 静态链接 SQLite, 真正零配置
//! - WAL 模式 + busy_timeout 处理并发
//! - 不使用 INSERT OR REPLACE (FK CASCADE 问题), 改用 SELECT + INSERT/UPDATE

use crate::events::{Event, EventStatus, EventType, Trace};
use anyhow::{Context, Result};
use rusqlite::{params, Connection, OptionalExtension, Row};
use std::path::Path;
use std::sync::Arc;
use tokio::sync::Mutex;

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vibe TEXT DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_ms REAL,
    status TEXT DEFAULT 'ok',
    error TEXT,
    input TEXT,
    output TEXT,
    total_events INTEGER DEFAULT 0,
    total_llm_calls INTEGER DEFAULT 0,
    total_tool_calls INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    error_count INTEGER DEFAULT 0,
    metadata TEXT,
    tags TEXT,
    analyst_report TEXT,
    analyst_run_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_start_time ON traces(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_id TEXT,
    span_id TEXT,
    event_type TEXT NOT NULL,
    name TEXT,
    status TEXT DEFAULT 'ok',
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_ms REAL,
    input TEXT,
    output TEXT,
    error TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    tool_name TEXT,
    metadata TEXT,
    tags TEXT,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id, start_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
"#;

pub struct Store {
    conn: Arc<Mutex<Connection>>,
}

impl Store {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self> {
        let conn = Connection::open(path.as_ref())
            .with_context(|| format!("Failed to open SQLite at {:?}", path.as_ref()))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.pragma_update(None, "busy_timeout", 5000)?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub async fn save_event(&self, event: &Event) -> Result<()> {
        let conn = self.conn.clone();
        let event = event.clone();
        tokio::task::spawn_blocking(move || -> Result<()> {
            let conn = conn.blocking_lock();
            save_event_sync(&conn, &event)
        })
        .await??;
        Ok(())
    }

    pub async fn save_trace(&self, trace: &Trace) -> Result<()> {
        let conn = self.conn.clone();
        let trace = trace.clone();
        tokio::task::spawn_blocking(move || -> Result<()> {
            let conn = conn.blocking_lock();
            save_trace_sync(&conn, &trace)
        })
        .await??;
        // Force checkpoint 让其他 connection 可见
        self.checkpoint().await?;
        Ok(())
    }

    pub async fn checkpoint(&self) -> Result<()> {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || -> Result<()> {
            let conn = conn.blocking_lock();
            conn.pragma_update(None, "wal_checkpoint", "PASSIVE")?;
            Ok(())
        })
        .await??;
        Ok(())
    }

    pub async fn list_traces(&self, limit: u32) -> Result<Vec<Trace>> {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || -> Result<Vec<Trace>> {
            let conn = conn.blocking_lock();
            let mut stmt = conn.prepare("SELECT * FROM traces ORDER BY start_time DESC LIMIT ?")?;
            let rows = stmt.query_map(params![limit as i64], row_to_trace)?;
            rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
        })
        .await?
    }

    pub async fn get_trace(&self, trace_id: &str) -> Result<Option<Trace>> {
        let conn = self.conn.clone();
        let trace_id = trace_id.to_string();
        tokio::task::spawn_blocking(move || -> Result<Option<Trace>> {
            let conn = conn.blocking_lock();
            conn.query_row(
                "SELECT * FROM traces WHERE trace_id = ?",
                params![trace_id],
                row_to_trace,
            )
            .optional()
            .map_err(Into::into)
        })
        .await?
    }

    pub async fn get_events(&self, trace_id: &str) -> Result<Vec<Event>> {
        let conn = self.conn.clone();
        let trace_id = trace_id.to_string();
        tokio::task::spawn_blocking(move || -> Result<Vec<Event>> {
            let conn = conn.blocking_lock();
            let mut stmt = conn.prepare(
                "SELECT * FROM events WHERE trace_id = ? ORDER BY start_time ASC, event_id ASC",
            )?;
            let rows = stmt.query_map(params![trace_id], row_to_event)?;
            rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
        })
        .await?
    }

    pub async fn get_stats(&self) -> Result<Stats> {
        let conn = self.conn.clone();
        tokio::task::spawn_blocking(move || -> Result<Stats> {
            let conn = conn.blocking_lock();
            let row = conn.query_row(
                r#"
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                    COALESCE(SUM(total_tokens), 0) as tokens,
                    COALESCE(SUM(total_cost_usd), 0.0) as cost,
                    COALESCE(SUM(total_llm_calls), 0) as llm,
                    COALESCE(SUM(total_tool_calls), 0) as tools,
                    COALESCE(AVG(duration_ms), 0.0) as avg_dur
                FROM traces
                "#,
                [],
                |r| {
                    Ok(Stats {
                        total_traces: r.get(0)?,
                        error_traces: r.get::<_, Option<i64>>(1)?.unwrap_or(0),
                        total_tokens: r.get(2)?,
                        total_cost_usd: r.get(3)?,
                        total_llm_calls: r.get(4)?,
                        total_tool_calls: r.get(5)?,
                        avg_duration_ms: r.get(6)?,
                    })
                },
            )?;
            Ok(row)
        })
        .await?
    }

    pub async fn save_analyst_report(&self, trace_id: &str, report: &str) -> Result<()> {
        let conn = self.conn.clone();
        let trace_id = trace_id.to_string();
        let report = report.to_string();
        tokio::task::spawn_blocking(move || -> Result<()> {
            let conn = conn.blocking_lock();
            conn.execute(
                "UPDATE traces SET analyst_report = ?, analyst_run_at = ? WHERE trace_id = ?",
                params![report, chrono::Utc::now().to_rfc3339(), trace_id],
            )?;
            Ok(())
        })
        .await?
    }

    pub async fn get_analyst_report(&self, trace_id: &str) -> Result<Option<String>> {
        let conn = self.conn.clone();
        let trace_id = trace_id.to_string();
        tokio::task::spawn_blocking(move || -> Result<Option<String>> {
            let conn = conn.blocking_lock();
            conn.query_row(
                "SELECT analyst_report FROM traces WHERE trace_id = ?",
                params![trace_id],
                |r| r.get(0),
            )
            .optional()
            .map_err(Into::into)
        })
        .await?
    }

    pub async fn delete_trace(&self, trace_id: &str) -> Result<()> {
        let conn = self.conn.clone();
        let trace_id = trace_id.to_string();
        tokio::task::spawn_blocking(move || -> Result<()> {
            let conn = conn.blocking_lock();
            conn.execute("DELETE FROM events WHERE trace_id = ?", params![trace_id])?;
            conn.execute("DELETE FROM traces WHERE trace_id = ?", params![trace_id])?;
            Ok(())
        })
        .await?
    }
}

#[derive(Debug, Serialize)]
pub struct Stats {
    pub total_traces: i64,
    pub error_traces: i64,
    pub total_tokens: i64,
    pub total_cost_usd: f64,
    pub total_llm_calls: i64,
    pub total_tool_calls: i64,
    pub avg_duration_ms: f64,
}

// === Sync helpers ===

fn save_event_sync(conn: &Connection, event: &Event) -> Result<()> {
    let input_json = event
        .input
        .as_ref()
        .map(|v| v.to_string())
        .unwrap_or_default();
    let output_json = event
        .output
        .as_ref()
        .map(|v| v.to_string())
        .unwrap_or_default();
    let metadata_json = serde_json::to_string(&event.metadata)?;
    let tags_json = serde_json::to_string(&event.tags)?;

    // 关键: 不使用 INSERT OR REPLACE (FK CASCADE 问题)
    let existing: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM events WHERE event_id = ?",
            params![event.event_id],
            |_| Ok(1),
        )
        .optional()?;

    if existing.is_some() {
        conn.execute(
            r#"
            UPDATE events SET
                trace_id = ?1, parent_id = ?2, span_id = ?3, event_type = ?4,
                name = ?5, status = ?6, start_time = ?7, end_time = ?8, duration_ms = ?9,
                input = ?10, output = ?11, error = ?12,
                model = ?13, prompt_tokens = ?14, completion_tokens = ?15,
                total_tokens = ?16, cost_usd = ?17, tool_name = ?18,
                metadata = ?19, tags = ?20
            WHERE event_id = ?21
            "#,
            params![
                event.trace_id,
                event.parent_id,
                event.span_id,
                event.event_type.as_str(),
                event.name,
                event.status.as_str(),
                event.start_time.to_rfc3339(),
                event.end_time.map(|t| t.to_rfc3339()),
                event.duration_ms,
                input_json,
                output_json,
                event.error,
                event.model,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                event.cost_usd,
                event.tool_name,
                metadata_json,
                tags_json,
                event.event_id,
            ],
        )?;
    } else {
        conn.execute(
            r#"
            INSERT INTO events (
                event_id, trace_id, parent_id, span_id, event_type, name, status,
                start_time, end_time, duration_ms, input, output, error,
                model, prompt_tokens, completion_tokens, total_tokens, cost_usd,
                tool_name, metadata, tags
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13,
                      ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21)
            "#,
            params![
                event.event_id,
                event.trace_id,
                event.parent_id,
                event.span_id,
                event.event_type.as_str(),
                event.name,
                event.status.as_str(),
                event.start_time.to_rfc3339(),
                event.end_time.map(|t| t.to_rfc3339()),
                event.duration_ms,
                input_json,
                output_json,
                event.error,
                event.model,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                event.cost_usd,
                event.tool_name,
                metadata_json,
                tags_json,
            ],
        )?;
    }
    Ok(())
}

fn save_trace_sync(conn: &Connection, trace: &Trace) -> Result<()> {
    let input_json = trace
        .input
        .as_ref()
        .map(|v| v.to_string())
        .unwrap_or_default();
    let output_json = trace
        .output
        .as_ref()
        .map(|v| v.to_string())
        .unwrap_or_default();
    let metadata_json = serde_json::to_string(&trace.metadata)?;
    let tags_json = serde_json::to_string(&trace.tags)?;

    let existing: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM traces WHERE trace_id = ?",
            params![trace.trace_id],
            |_| Ok(1),
        )
        .optional()?;

    if existing.is_some() {
        conn.execute(
            r#"
            UPDATE traces SET
                name = ?1, vibe = ?2, start_time = ?3, end_time = ?4, duration_ms = ?5,
                status = ?6, error = ?7, input = ?8, output = ?9,
                total_events = ?10, total_llm_calls = ?11, total_tool_calls = ?12,
                total_tokens = ?13, total_cost_usd = ?14, error_count = ?15,
                metadata = ?16, tags = ?17
            WHERE trace_id = ?18
            "#,
            params![
                trace.name,
                trace.vibe,
                trace.start_time.to_rfc3339(),
                trace.end_time.map(|t| t.to_rfc3339()),
                trace.duration_ms,
                trace.status.as_str(),
                trace.error,
                input_json,
                output_json,
                trace.total_events,
                trace.total_llm_calls,
                trace.total_tool_calls,
                trace.total_tokens,
                trace.total_cost_usd,
                trace.error_count,
                metadata_json,
                tags_json,
                trace.trace_id,
            ],
        )?;
    } else {
        conn.execute(
            r#"
            INSERT INTO traces (
                trace_id, name, vibe, start_time, end_time, duration_ms,
                status, error, input, output,
                total_events, total_llm_calls, total_tool_calls, total_tokens,
                total_cost_usd, error_count, metadata, tags
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13,
                      ?14, ?15, ?16, ?17, ?18)
            "#,
            params![
                trace.trace_id,
                trace.name,
                trace.vibe,
                trace.start_time.to_rfc3339(),
                trace.end_time.map(|t| t.to_rfc3339()),
                trace.duration_ms,
                trace.status.as_str(),
                trace.error,
                input_json,
                output_json,
                trace.total_events,
                trace.total_llm_calls,
                trace.total_tool_calls,
                trace.total_tokens,
                trace.total_cost_usd,
                trace.error_count,
                metadata_json,
                tags_json,
            ],
        )?;
    }
    Ok(())
}

fn row_to_trace(row: &Row) -> rusqlite::Result<Trace> {
    let trace_id: String = row.get("trace_id")?;
    let name: String = row.get("name")?;
    let vibe: String = row.get("vibe").unwrap_or_default();
    let start_time_str: String = row.get("start_time")?;
    let end_time_str: Option<String> = row.get("end_time")?;
    let duration_ms: Option<f64> = row.get("duration_ms")?;
    let status_str: String = row.get("status").unwrap_or_else(|_| "ok".to_string());
    let error: Option<String> = row.get("error")?;
    let input_str: String = row.get("input").unwrap_or_default();
    let output_str: String = row.get("output").unwrap_or_default();
    let total_events: i64 = row.get("total_events").unwrap_or(0);
    let total_llm_calls: i64 = row.get("total_llm_calls").unwrap_or(0);
    let total_tool_calls: i64 = row.get("total_tool_calls").unwrap_or(0);
    let total_tokens: i64 = row.get("total_tokens").unwrap_or(0);
    let total_cost_usd: f64 = row.get("total_cost_usd").unwrap_or(0.0);
    let error_count: i64 = row.get("error_count").unwrap_or(0);
    let metadata_str: String = row.get("metadata").unwrap_or_default();
    let tags_str: String = row.get("tags").unwrap_or_default();

    Ok(Trace {
        trace_id,
        name,
        vibe,
        start_time: parse_dt(&start_time_str),
        end_time: end_time_str.as_ref().map(|s| parse_dt(s)),
        duration_ms,
        input: parse_json(&input_str),
        output: parse_json(&output_str),
        status: parse_status(&status_str),
        error,
        total_events: total_events as u32,
        total_llm_calls: total_llm_calls as u32,
        total_tool_calls: total_tool_calls as u32,
        total_tokens: total_tokens as u32,
        total_cost_usd,
        error_count: error_count as u32,
        metadata: parse_json(&metadata_str)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default(),
        tags: parse_json(&tags_str)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default(),
    })
}

fn row_to_event(row: &Row) -> rusqlite::Result<Event> {
    let event_id: String = row.get("event_id")?;
    let trace_id: String = row.get("trace_id")?;
    let parent_id: Option<String> = row.get("parent_id")?;
    let span_id: String = row.get("span_id").unwrap_or_default();
    let event_type_str: String = row.get("event_type")?;
    let name: String = row.get("name").unwrap_or_default();
    let status_str: String = row.get("status").unwrap_or_else(|_| "ok".to_string());
    let start_time_str: String = row.get("start_time")?;
    let end_time_str: Option<String> = row.get("end_time")?;
    let duration_ms: Option<f64> = row.get("duration_ms")?;
    let input_str: String = row.get("input").unwrap_or_default();
    let output_str: String = row.get("output").unwrap_or_default();
    let error: Option<String> = row.get("error")?;
    let model: Option<String> = row.get("model")?;
    let prompt_tokens: Option<i64> = row.get("prompt_tokens")?;
    let completion_tokens: Option<i64> = row.get("completion_tokens")?;
    let total_tokens: Option<i64> = row.get("total_tokens")?;
    let cost_usd: Option<f64> = row.get("cost_usd")?;
    let tool_name: Option<String> = row.get("tool_name")?;
    let metadata_str: String = row.get("metadata").unwrap_or_default();
    let tags_str: String = row.get("tags").unwrap_or_default();

    Ok(Event {
        event_id,
        trace_id,
        parent_id,
        span_id,
        event_type: parse_event_type(&event_type_str),
        name,
        status: parse_status(&status_str),
        start_time: parse_dt(&start_time_str),
        end_time: end_time_str.as_ref().map(|s| parse_dt(s)),
        duration_ms,
        input: parse_json(&input_str),
        output: parse_json(&output_str),
        error,
        model,
        prompt_tokens: prompt_tokens.map(|n| n as u32),
        completion_tokens: completion_tokens.map(|n| n as u32),
        total_tokens: total_tokens.map(|n| n as u32),
        cost_usd,
        tool_name,
        metadata: parse_json(&metadata_str)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default(),
        tags: parse_json(&tags_str)
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default(),
    })
}

fn parse_dt(s: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(s)
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|_| Utc::now())
}

fn parse_json(s: &str) -> Option<serde_json::Value> {
    if s.is_empty() {
        return None;
    }
    serde_json::from_str(s).ok()
}

fn parse_status(s: &str) -> EventStatus {
    match s {
        "error" => EventStatus::Error,
        "timeout" => EventStatus::Timeout,
        "cancelled" => EventStatus::Cancelled,
        _ => EventStatus::Ok,
    }
}

fn parse_event_type(s: &str) -> EventType {
    match s {
        "trace.start" => EventType::TraceStart,
        "trace.end" => EventType::TraceEnd,
        "llm.call" => EventType::LlmCall,
        "tool.call" => EventType::ToolCall,
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

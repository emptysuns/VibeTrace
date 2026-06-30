//! VibeTrace - 追踪引擎
//!
//! 负责维护 active trace/event 状态, 由 Tracer 单例管理.
//! 关键设计: 同一进程内, 多个 trace 可以嵌套 (parent-child), 通过
//! Mutex<Vec<TraceContext>> 维护栈式结构.

use crate::events::{Event, EventStatus, EventType, Trace};
use crate::store::Store;
use anyhow::Result;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct ActiveEvent {
    pub event: Event,
    pub started_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug)]
pub struct ActiveTrace {
    pub trace: Trace,
    pub events: Vec<Event>,
    pub loop_counter: HashMap<String, u32>,
}

impl ActiveTrace {
    pub fn new(name: impl Into<String>, vibe: impl Into<String>) -> Self {
        Self {
            trace: Trace::new(name, vibe),
            events: Vec::new(),
            loop_counter: HashMap::new(),
        }
    }

    pub fn add_event(&mut self, event: Event) {
        // Update aggregate stats
        if event.event_type == EventType::LlmCall {
            self.trace.total_llm_calls += 1;
            if let Some(cost) = event.cost_usd {
                self.trace.total_cost_usd += cost;
            }
            if let Some(tokens) = event.total_tokens {
                self.trace.total_tokens += tokens;
            }
        }
        if event.event_type == EventType::ToolCall {
            self.trace.total_tool_calls += 1;
        }
        if event.status == EventStatus::Error {
            self.trace.error_count += 1;
        }
        self.trace.total_events += 1;
        self.events.push(event);
    }
}

pub struct Tracer {
    store: Arc<Store>,
    active_traces: Mutex<Vec<ActiveTrace>>,
    active_spans: Mutex<Vec<ActiveEvent>>,
    loop_threshold: u32,
}

impl Tracer {
    pub fn new(store: Arc<Store>, loop_threshold: u32) -> Self {
        Self {
            store,
            active_traces: Mutex::new(Vec::new()),
            active_spans: Mutex::new(Vec::new()),
            loop_threshold,
        }
    }

    pub fn store(&self) -> Arc<Store> {
        self.store.clone()
    }

    pub async fn start_trace(
        &self,
        name: String,
        vibe: String,
        input: Option<serde_json::Value>,
    ) -> Result<String> {
        let mut trace = ActiveTrace::new(name.clone(), vibe);
        trace.trace.input = input;

        let trace_id = trace.trace.trace_id.clone();

        // Save trace row first (for FK)
        self.store.save_trace(&trace.trace).await?;

        // Save trace.start event
        let mut start_event = Event::new(EventType::TraceStart, &name, &trace_id);
        start_event.input = trace.trace.input.clone();
        self.store.save_event(&start_event).await?;
        trace.add_event(start_event);

        let mut traces = self.active_traces.lock().await;
        traces.push(trace);
        Ok(trace_id)
    }

    pub async fn end_trace(&self, trace_id: &str, output: Option<serde_json::Value>) -> Result<()> {
        let mut traces = self.active_traces.lock().await;
        let pos = traces
            .iter()
            .position(|t| t.trace.trace_id == trace_id)
            .ok_or_else(|| anyhow::anyhow!("Trace {} not found", trace_id))?;

        let mut trace = traces.remove(pos);

        trace.trace.output = output;
        trace.trace.finish(EventStatus::Ok);
        self.store.save_trace(&trace.trace).await?;

        // Save trace.end event
        let end_event = Event::new(EventType::TraceEnd, &trace.trace.name, &trace_id);
        let _ = self.store.save_event(&end_event).await;

        Ok(())
    }

    pub async fn record_event(
        &self,
        trace_id: Option<&str>,
        name: String,
        event_type: EventType,
        input: Option<serde_json::Value>,
        output: Option<serde_json::Value>,
        metadata: HashMap<String, serde_json::Value>,
    ) -> Result<String> {
        // Find the trace - if trace_id given, find that one; otherwise use top
        let target_trace_id = match trace_id {
            Some(id) => id.to_string(),
            None => {
                let traces = self.active_traces.lock().await;
                traces
                    .last()
                    .ok_or_else(|| anyhow::anyhow!("No active trace"))?
                    .trace
                    .trace_id
                    .clone()
            }
        };

        let parent_id = {
            let spans = self.active_spans.lock().await;
            spans.last().map(|s| s.event.span_id.clone())
        };

        let mut event = Event::new(event_type, name, &target_trace_id);
        event.parent_id = parent_id;
        event.input = input;
        event.output = output;
        event.metadata = metadata.clone();

        // Loop detection for reasoning events
        if event_type == EventType::Reasoning {
            if let Some(serde_json::Value::String(s)) = &event.input {
                let sig: String = s.chars().take(200).collect();
                let mut traces = self.active_traces.lock().await;
                if let Some(at) = traces
                    .iter_mut()
                    .find(|t| t.trace.trace_id == target_trace_id)
                {
                    let count = at.loop_counter.entry(sig.clone()).or_insert(0);
                    *count += 1;
                    if *count >= self.loop_threshold {
                        event
                            .metadata
                            .insert("loop_detected".to_string(), serde_json::json!(true));
                        event
                            .metadata
                            .insert("loop_count".to_string(), serde_json::json!(*count));
                    }
                }
            }
        }

        // Estimate cost for known models
        if event_type == EventType::LlmCall {
            if let Some(model) = event.metadata.get("model").and_then(|v| v.as_str()) {
                event.model = Some(model.to_string());
                if let (Some(p), Some(c)) = (
                    event.metadata.get("prompt_tokens").and_then(|v| v.as_u64()),
                    event
                        .metadata
                        .get("completion_tokens")
                        .and_then(|v| v.as_u64()),
                ) {
                    event.prompt_tokens = Some(p as u32);
                    event.completion_tokens = Some(c as u32);
                    event.total_tokens = Some((p + c) as u32);
                    event.cost_usd = Some(estimate_cost(model, p, c));
                }
            }
        }

        if event_type == EventType::ToolCall {
            if let Some(tool) = event.metadata.get("tool_name").and_then(|v| v.as_str()) {
                event.tool_name = Some(tool.to_string());
            }
        }

        self.store.save_event(&event).await?;

        let event_id = event.event_id.clone();

        // Add to active trace
        {
            let mut traces = self.active_traces.lock().await;
            if let Some(at) = traces
                .iter_mut()
                .find(|t| t.trace.trace_id == target_trace_id)
            {
                at.add_event(event.clone());
                // Persist updated stats
                let _ = self.store.save_trace(&at.trace).await;
            }
        }

        Ok(event_id)
    }

    pub async fn finish_event(
        &self,
        event_id: &str,
        output: Option<serde_json::Value>,
        error: Option<String>,
    ) -> Result<()> {
        // Find event in active spans
        {
            let mut spans = self.active_spans.lock().await;
            for span in spans.iter_mut() {
                if span.event.event_id == event_id {
                    span.event.output = output.clone().or(span.event.output.clone());
                    if let Some(err) = &error {
                        span.event.status = EventStatus::Error;
                        span.event.error = Some(err.clone());
                    }
                    span.event.finish(EventStatus::Ok);
                    let _ = self.store.save_event(&span.event).await;
                    return Ok(());
                }
            }
        }
        Ok(())
    }
}

fn estimate_cost(model: &str, prompt_tokens: u64, completion_tokens: u64) -> f64 {
    // Per 1M tokens (2026 prices)
    let (input_price, output_price) = match model {
        m if m.starts_with("claude-opus-4") => (15.0, 75.0),
        m if m.starts_with("claude-sonnet-4") => (3.0, 15.0),
        m if m.starts_with("claude-haiku-4") => (0.25, 1.25),
        m if m.starts_with("claude-opus") => (15.0, 75.0),
        m if m.starts_with("claude-sonnet") => (3.0, 15.0),
        m if m.starts_with("claude-haiku") => (0.25, 1.25),
        m if m.starts_with("gpt-4o") => (5.0, 15.0),
        m if m.starts_with("gpt-4") => (10.0, 30.0),
        m if m.starts_with("gpt-3.5") => (0.5, 1.5),
        _ => return 0.0,
    };
    (prompt_tokens as f64 * input_price + completion_tokens as f64 * output_price) / 1_000_000.0
}

//! VibeTrace - 分析师
//!
//! 规则引擎 + LLM 增强 (后者未来扩展). 当下 MVP 用规则引擎, 零依赖.

use crate::events::{Event, EventStatus, EventType, Trace};
use serde::Serialize;

#[derive(Serialize)]
pub struct AnalystReport {
    pub trace_id: String,
    pub summary: String,
    pub root_cause: Option<String>,
    pub patterns: Vec<PatternFinding>,
    pub suggestions: Vec<String>,
    pub vibe_deviation: Vec<String>,
    pub markdown: String,
}

#[derive(Serialize)]
pub struct PatternFinding {
    pub kind: String,
    pub message: String,
    pub severity: String,
}

pub fn analyze(t: &Trace, events: &[Event]) -> AnalystReport {
    let summary = format!(
        "{} **{}** ({}ms, {} events, ${:.4}, {} tokens){}",
        if t.status == EventStatus::Ok { "✅" } else { "❌" },
        t.name,
        t.duration_ms.map(|d| d as u64).unwrap_or(0),
        t.total_events,
        t.total_cost_usd,
        t.total_tokens,
        if !t.vibe.is_empty() {
            format!("\n🎨 Vibe: *{}*", t.vibe)
        } else {
            String::new()
        }
    );

    // 根因分析: 第一个 error event
    let root_cause = events
        .iter()
        .find(|e| e.status == EventStatus::Error)
        .map(|e| format!("首个错误: `{}` ({})\n> {}", e.name, e.event_type.as_str(), e.error.clone().unwrap_or_default()));

    // 模式检测
    let mut patterns = Vec::new();

    // Loop detection
    let mut counter: std::collections::HashMap<String, u32> = std::collections::HashMap::new();
    for e in events.iter().filter(|e| e.event_type == EventType::Reasoning) {
        if let Some(serde_json::Value::String(s)) = &e.input {
            let sig: String = s.chars().take(100).collect();
            if !sig.is_empty() {
                *counter.entry(sig).or_insert(0) += 1;
            }
        }
    }
    let loops: Vec<_> = counter.iter().filter(|(_, c)| **c >= 3).collect();
    if !loops.is_empty() {
        patterns.push(PatternFinding {
            kind: "loop".into(),
            message: format!("检测到 {} 个 reasoning 重复 ≥3 次", loops.len()),
            severity: "high".into(),
        });
    }

    // Cost hotspot
    if let Some(top) = events.iter()
        .filter(|e| e.event_type == EventType::LlmCall && e.cost_usd.is_some())
        .max_by(|a, b| a.cost_usd.partial_cmp(&b.cost_usd).unwrap_or(std::cmp::Ordering::Equal))
    {
        patterns.push(PatternFinding {
            kind: "cost".into(),
            message: format!(
                "Cost hotspot: `{}` 花费 ${:.4} ({} tokens)",
                top.name, top.cost_usd.unwrap_or(0.0), top.total_tokens.unwrap_or(0)
            ),
            severity: "medium".into(),
        });
    }

    // Slow step
    if let Some(top) = events.iter()
        .filter(|e| e.duration_ms.is_some() && e.duration_ms.unwrap() > 100.0)
        .max_by(|a, b| a.duration_ms.partial_cmp(&b.duration_ms).unwrap_or(std::cmp::Ordering::Equal))
    {
        patterns.push(PatternFinding {
            kind: "slow".into(),
            message: format!("Slow step: `{}` 耗时 {}ms", top.name, top.duration_ms.unwrap() as u64),
            severity: "low".into(),
        });
    }

    // Error rate
    if t.error_count > 0 {
        let rate = t.error_count as f64 / t.total_events.max(1) as f64 * 100.0;
        patterns.push(PatternFinding {
            kind: "error_rate".into(),
            message: format!("Error rate: {}/{} = {:.1}%", t.error_count, t.total_events, rate),
            severity: if rate > 20.0 { "high".into() } else { "medium".into() },
        });
    }

    // 改进建议
    let mut suggestions = Vec::new();
    if !loops.is_empty() {
        suggestions.push("🔁 添加 max iterations 限制, 避免无限循环".into());
        suggestions.push("🧠 在 prompt 中加 '如发现重复, 改变策略' 指令".into());
    }
    if t.total_cost_usd > 1.0 {
        suggestions.push(format!("💰 单次 trace 成本 ${:.2} 偏高, 考虑用更便宜 model 或减少 LLM 次数", t.total_cost_usd));
    }
    if t.error_count > 0 {
        suggestions.push("🛡️ 添加 retry + fallback (exponential backoff)".into());
        suggestions.push("📋 给 tool call 加 JSON schema, 让 LLM 输出更可预测".into());
    }
    if t.total_llm_calls > 10 {
        suggestions.push(format!("🤖 调了 {} 次 LLM, 考虑 batch 多个 sub-task", t.total_llm_calls));
    }
    if suggestions.is_empty() {
        suggestions.push("✨ 看起来很健康, 持续监控即可".into());
    }

    // Vibe 偏离
    let mut vibe_deviation = Vec::new();
    if !t.vibe.is_empty() {
        let outputs: String = events.iter()
            .filter_map(|e| e.output.as_ref().map(|v| v.to_string()))
            .collect::<Vec<_>>()
            .join(" ");
        let vl = t.vibe.to_lowercase();

        if (vl.contains("minimalist") || vl.contains("minimal") || vl.contains("简洁"))
            && outputs.len() > 5000
        {
            vibe_deviation.push("输出过长, 可能违反 'minimalist' vibe".into());
        }
        if (vl.contains("calm") || vl.contains("平静"))
            && ["urgent", "panic", "asap", "crash", "崩溃", "急"]
                .iter().any(|w| outputs.to_lowercase().contains(w))
        {
            vibe_deviation.push("输出含 panic/urgent 词汇, 与 'calm' vibe 冲突".into());
        }
        if (vl.contains("professional") || vl.contains("专业"))
            && ["lol", "haha", "omg", "嘿嘿", "yeah"]
                .iter().any(|w| outputs.to_lowercase().contains(w))
        {
            vibe_deviation.push("输出含非正式词汇, 与 'professional' vibe 冲突".into());
        }
    }

    // 组装 markdown
    let mut md = String::new();
    md.push_str("# VibeTrace Analyst Report\n\n");
    md.push_str("> 🪄 Calm, insightful, minimalist.\n\n");
    md.push_str("## 执行摘要\n");
    md.push_str(&summary);
    md.push_str("\n\n");
    if let Some(rc) = &root_cause {
        md.push_str("## 根因分析\n");
        md.push_str(rc);
        md.push_str("\n\n");
    }
    if !patterns.is_empty() {
        md.push_str("## 模式检测\n");
        for p in &patterns {
            let icon = match p.severity.as_str() {
                "high" => "🔴",
                "medium" => "🟡",
                _ => "🟢",
            };
            md.push_str(&format!("{} **{}**: {}\n", icon, p.kind, p.message));
        }
        md.push_str("\n");
    }
    if !suggestions.is_empty() {
        md.push_str("## 改进建议\n");
        for s in &suggestions {
            md.push_str(&format!("- {}\n", s));
        }
        md.push_str("\n");
    }
    if !t.vibe.is_empty() {
        md.push_str("## Vibe 偏离检测\n");
        md.push_str(&format!("原始 vibe: *{}*\n", t.vibe));
        if vibe_deviation.is_empty() {
            md.push_str("- ✅ 未发现明显 vibe 偏离\n");
        } else {
            for d in &vibe_deviation {
                md.push_str(&format!("- ⚠️ {}\n", d));
            }
        }
        md.push_str("\n");
    }

    AnalystReport {
        trace_id: t.trace_id.clone(),
        summary,
        root_cause,
        patterns,
        suggestions,
        vibe_deviation,
        markdown: md,
    }
}

import { useEffect, useState, useCallback } from "react";
import * as api from "./api";
import type { Trace, Event, Stats, AnalystReport } from "./api";

const EVENT_EMOJI: Record<string, string> = {
  "trace.start": "▶️",
  "trace.end": "⏹️",
  "llm.call": "🤖",
  "tool.call": "🔧",
  reasoning: "💭",
  "memory.read": "📖",
  "memory.write": "✏️",
  decision: "🔀",
  error: "❌",
  retry: "🔁",
  "human.input": "👤",
};

function fmtDuration(ms: number | null | undefined): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  return `${(ms / 60000).toFixed(2)}min`;
}

function fmtCost(c: number | null | undefined): string {
  if (!c) return "$0.00";
  if (c < 0.01) return `$${c.toFixed(4)}`;
  return `$${c.toFixed(2)}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString();
}

function eventClass(e: Event): string {
  if (e.status === "error") return "error";
  if (e.event_type === "llm.call") return "llm";
  if (e.event_type === "tool.call") return "tool";
  if (e.event_type === "reasoning") return "reasoning";
  return "";
}

export default function App() {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [tab, setTab] = useState<"timeline" | "graph" | "analyst" | "vibe">("timeline");
  const [analyst, setAnalyst] = useState<AnalystReport | null>(null);
  const [search, setSearch] = useState("");
  const [setupStatus, setSetupStatus] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api.listTraces(100), api.getStats()]);
      setTraces(t);
      setStats(s);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000); // poll every 3s
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedTrace(null);
      setEvents([]);
      setAnalyst(null);
      return;
    }
    (async () => {
      try {
        const [t, evs] = await Promise.all([
          api.getTrace(selectedId),
          api.getEvents(selectedId),
        ]);
        setSelectedTrace(t);
        setEvents(evs);
        setAnalyst(null);
      } catch (e) {
        console.error(e);
      }
    })();
  }, [selectedId]);

  useEffect(() => {
    if (tab === "analyst" && selectedId && !analyst) {
      api.analyzeTrace(selectedId).then(setAnalyst).catch(console.error);
    }
  }, [tab, selectedId, analyst]);

  const filteredTraces = traces.filter((t) =>
    !search || t.name.toLowerCase().includes(search.toLowerCase())
  );

  const setupClaudeCode = async () => {
    try {
      const msg = await api.initClaudeCodeHooks(7842);
      setSetupStatus(msg);
      setTimeout(() => setSetupStatus(null), 5000);
    } catch (e: any) {
      setSetupStatus(`Error: ${e.toString()}`);
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>🪄 VibeTrace</h1>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            AI Agent observability
          </div>
        </div>

        {stats && (
          <div className="sidebar-stats">
            <div className="metric">
              <div className="metric-label">Traces</div>
              <div className="metric-value">{stats.total_traces}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Errors</div>
              <div className="metric-value" style={{ color: stats.error_traces > 0 ? "var(--accent-red)" : undefined }}>
                {stats.error_traces}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Tokens</div>
              <div className="metric-value">{stats.total_tokens.toLocaleString()}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Cost</div>
              <div className="metric-value">{fmtCost(stats.total_cost_usd)}</div>
            </div>
          </div>
        )}

        <div className="sidebar-controls">
          <input
            placeholder="🔍 search traces..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--border)" }}>
          <button className="primary" style={{ width: "100%" }} onClick={setupClaudeCode}>
            ⚡ Setup Claude Code Hooks
          </button>
          {setupStatus && (
            <div style={{ fontSize: 11, marginTop: 6, color: "var(--accent-green)" }}>
              ✅ {setupStatus}
            </div>
          )}
        </div>

        <div className="trace-list">
          {filteredTraces.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-secondary)", fontSize: 12 }}>
              No traces yet.<br />
              Run an agent or click "Setup Claude Code Hooks" above.
            </div>
          ) : (
            filteredTraces.map((t) => (
              <div
                key={t.trace_id}
                className={`trace-item ${selectedId === t.trace_id ? "active" : ""}`}
                onClick={() => setSelectedId(t.trace_id)}
              >
                <div className="trace-name">
                  <span className={t.status === "ok" ? "status-ok" : "status-error"}>
                    {t.status === "ok" ? "✅" : "❌"}
                  </span>
                  {t.name}
                </div>
                {t.vibe && <span className="vibe-badge">🎨 {t.vibe}</span>}
                <div className="trace-meta">
                  <span>⏱️ {fmtDuration(t.duration_ms)}</span>
                  <span>🤖 {t.total_llm_calls}</span>
                  <span>🔧 {t.total_tool_calls}</span>
                  <span>💰 {fmtCost(t.total_cost_usd)}</span>
                  <span>🕐 {fmtTime(t.start_time)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className="main">
        {!selectedTrace ? (
          <div className="empty-state">
            <div style={{ fontSize: 48 }}>🪄</div>
            <h2>VibeTrace</h2>
            <p>
              Calm, insightful, minimalist observability for AI Agents.
            </p>
            <p style={{ fontSize: 12, maxWidth: 500, lineHeight: 1.6 }}>
              Connect to Claude Code by clicking <strong>"Setup Claude Code Hooks"</strong> on the left.
              Or run <code style={{ color: "var(--accent-purple)" }}>vibetrace demo</code> in your terminal
              (the Python package) to populate traces.
            </p>
          </div>
        ) : (
          <>
            <div className="detail-header">
              <div>
                <div className="detail-title">
                  {selectedTrace.status === "ok" ? "✅" : "❌"} {selectedTrace.name}
                </div>
                {selectedTrace.vibe && (
                  <span className="vibe-badge" style={{ marginTop: 4, display: "inline-block" }}>
                    🎨 {selectedTrace.vibe}
                  </span>
                )}
                <div className="detail-stats">
                  <span className="detail-stat">⏱️ <strong>{fmtDuration(selectedTrace.duration_ms)}</strong></span>
                  <span className="detail-stat">📊 <strong>{selectedTrace.total_events}</strong> events</span>
                  <span className="detail-stat">🤖 <strong>{selectedTrace.total_llm_calls}</strong> LLM</span>
                  <span className="detail-stat">🔧 <strong>{selectedTrace.total_tool_calls}</strong> tools</span>
                  <span className="detail-stat">📊 <strong>{selectedTrace.total_tokens.toLocaleString()}</strong> tokens</span>
                  <span className="detail-stat">💰 <strong>{fmtCost(selectedTrace.total_cost_usd)}</strong></span>
                </div>
                {selectedTrace.error && (
                  <div style={{ color: "var(--accent-red)", marginTop: 8, fontSize: 12 }}>
                    ❌ {selectedTrace.error}
                  </div>
                )}
              </div>
              <button
                className="danger"
                onClick={async () => {
                  if (confirm("Delete this trace?")) {
                    await api.deleteTrace(selectedTrace.trace_id);
                    setSelectedId(null);
                    refresh();
                  }
                }}
              >
                🗑 Delete
              </button>
            </div>

            <div className="tabs">
              <div className={`tab ${tab === "timeline" ? "active" : ""}`} onClick={() => setTab("timeline")}>
                ⏱️ Timeline
              </div>
              <div className={`tab ${tab === "graph" ? "active" : ""}`} onClick={() => setTab("graph")}>
                🌳 Graph
              </div>
              <div className={`tab ${tab === "analyst" ? "active" : ""}`} onClick={() => setTab("analyst")}>
                🧠 Analyst
              </div>
              <div className={`tab ${tab === "vibe" ? "active" : ""}`} onClick={() => setTab("vibe")}>
                🎨 Vibe
              </div>
            </div>

            <div className="tab-content">
              {tab === "timeline" && (
                <TimelineView events={events} />
              )}
              {tab === "graph" && (
                <GraphView events={events} />
              )}
              {tab === "analyst" && (
                <AnalystView report={analyst} traceId={selectedTrace.trace_id} />
              )}
              {tab === "vibe" && (
                <VibeView trace={selectedTrace} events={events} />
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function TimelineView({ events }: { events: Event[] }) {
  if (events.length === 0) {
    return <div style={{ color: "var(--text-secondary)" }}>No events.</div>;
  }
  const baseTime = new Date(events[0].start_time).getTime();
  return (
    <div>
      {events.map((e, i) => {
        const offset = new Date(e.start_time).getTime() - baseTime;
        const emoji = EVENT_EMOJI[e.event_type] || "•";
        return (
          <div key={e.event_id} className={`event-card ${eventClass(e)}`}>
            <div className="event-header">
              <span>{emoji}</span>
              <span className="event-title">{e.event_type}</span>
              <span style={{ color: "var(--text-secondary)" }}>· {e.name}</span>
              {e.status === "error" && <span style={{ color: "var(--accent-red)" }}>❌</span>}
              <span style={{ marginLeft: "auto" }} className="event-time">
                +{offset}ms · {fmtDuration(e.duration_ms)}
              </span>
            </div>
            {(e.model || e.total_tokens || e.cost_usd) && (
              <div className="event-meta">
                {e.model && <span>🤖 {e.model}</span>}
                {e.total_tokens && <span>📊 {e.total_tokens} tokens</span>}
                {e.cost_usd && <span>💰 {fmtCost(e.cost_usd)}</span>}
                {e.tool_name && <span>🔧 {e.tool_name}</span>}
              </div>
            )}
            {(e.input || e.output || e.error) && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: "pointer", fontSize: 11, color: "var(--text-secondary)" }}>
                  Show details
                </summary>
                {e.input && (
                  <div className="event-detail">
                    <strong>Input:</strong> {JSON.stringify(e.input, null, 2).slice(0, 1000)}
                  </div>
                )}
                {e.output && (
                  <div className="event-detail">
                    <strong>Output:</strong> {JSON.stringify(e.output, null, 2).slice(0, 1000)}
                  </div>
                )}
                {e.error && (
                  <div className="event-detail" style={{ color: "var(--accent-red)" }}>
                    <strong>Error:</strong> {e.error}
                  </div>
                )}
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}

function GraphView({ events }: { events: Event[] }) {
  if (events.length === 0) {
    return <div style={{ color: "var(--text-secondary)" }}>No events.</div>;
  }
  const byParent: Record<string, Event[]> = {};
  const roots: Event[] = [];
  for (const e of events) {
    if (e.parent_id) {
      (byParent[e.parent_id] ||= []).push(e);
    } else {
      roots.push(e);
    }
  }
  const renderNode = (e: Event, depth: number): JSX.Element => {
    const children = byParent[e.span_id] || [];
    return (
      <div key={e.event_id}>
        <div style={{ paddingLeft: depth * 24, padding: "4px 0" }}>
          <span>{EVENT_EMOJI[e.event_type] || "•"}</span>{" "}
          <strong>{e.event_type}</strong>{" "}
          <span style={{ color: "var(--text-secondary)" }}>· {e.name}</span>{" "}
          <span style={{ color: "var(--text-secondary)", fontSize: 11 }}>{fmtDuration(e.duration_ms)}</span>
        </div>
        {children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };
  return <div>{roots.map((r) => renderNode(r, 0))}</div>;
}

function AnalystView({ report, traceId }: { report: AnalystReport | null; traceId: string }) {
  if (!report) {
    return (
      <div style={{ textAlign: "center", padding: 40, color: "var(--text-secondary)" }}>
        🧠 Analyzing trace...
      </div>
    );
  }
  // Render markdown as plain text with simple line-by-line parsing
  const lines = report.markdown.split("\n");
  return (
    <div className="analyst-report">
      {lines.map((line, i) => {
        if (line.startsWith("# ")) {
          return <h1 key={i} style={{ background: "var(--gradient)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>{line.slice(2)}</h1>;
        }
        if (line.startsWith("## ")) {
          return <h2 key={i}>{line.slice(3)}</h2>;
        }
        if (line.startsWith("> ")) {
          return <div key={i} style={{ borderLeft: "3px solid var(--accent-purple)", paddingLeft: 12, color: "var(--text-secondary)", fontStyle: "italic" }}>{line.slice(2)}</div>;
        }
        if (line.startsWith("- ")) {
          return <div key={i} style={{ paddingLeft: 8, margin: "4px 0" }}>• {line.slice(2)}</div>;
        }
        if (line.trim() === "") return <br key={i} />;
        return <div key={i}>{line}</div>;
      })}
    </div>
  );
}

function VibeView({ trace, events }: { trace: Trace; events: Event[] }) {
  if (!trace.vibe) {
    return (
      <div style={{ color: "var(--text-secondary)" }}>
        No vibe set for this trace.
      </div>
    );
  }
  const outputs = events
    .filter((e) => e.output)
    .map((e) => JSON.stringify(e.output))
    .join(" ");
  const vl = trace.vibe.toLowerCase();
  const ol = outputs.toLowerCase();
  const findings: string[] = [];
  if ((vl.includes("minimalist") || vl.includes("minimal") || vl.includes("简洁")) && outputs.length > 5000) {
    findings.push("⚠️ Output very long (" + outputs.length + " chars), may violate 'minimalist' vibe");
  }
  if ((vl.includes("calm") || vl.includes("平静")) && ["urgent", "panic", "asap", "crash", "崩溃"].some((w) => ol.includes(w))) {
    findings.push("⚠️ Output contains panic/urgent words, conflicts with 'calm' vibe");
  }
  if ((vl.includes("professional") || vl.includes("专业")) && ["lol", "haha", "omg", "嘿嘿"].some((w) => ol.includes(w))) {
    findings.push("⚠️ Output contains informal words, conflicts with 'professional' vibe");
  }
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>
          Original vibe
        </div>
        <span className="vibe-badge" style={{ fontSize: 14, padding: "6px 12px" }}>
          🎨 {trace.vibe}
        </span>
      </div>
      <h2 style={{ color: "var(--accent-purple)", marginBottom: 12 }}>Vibe Deviation Check</h2>
      {findings.length === 0 ? (
        <div style={{ color: "var(--accent-green)" }}>✅ No obvious vibe deviation detected.</div>
      ) : (
        findings.map((f, i) => <div key={i} style={{ marginBottom: 6, color: "var(--accent-yellow)" }}>{f}</div>)
      )}
      <div style={{ marginTop: 24, padding: 12, background: "var(--bg-card)", borderRadius: 6, fontSize: 12, color: "var(--text-secondary)" }}>
        💡 Vibe Check uses keyword heuristics. For deep LLM-powered analysis, set <code>ANTHROPIC_API_KEY</code> in the Python package and re-run.
      </div>
    </div>
  );
}

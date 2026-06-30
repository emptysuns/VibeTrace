import { useEffect, useState, useCallback } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  Play,
  Stop,
  Cpu,
  Wrench,
  Lightbulb,
  BookOpen,
  PencilSimple,
  Path,
  XCircle,
  ArrowClockwise,
  User,
  Dot,
  Timer,
  TreeStructure,
  Brain,
  PaintBrush,
  Plug,
  Trash,
  Coins,
  Clock,
  Hash,
  ChartBar,
  Waveform,
  Info,
  CheckCircle,
  Warning,
} from "@phosphor-icons/react";
import * as api from "./api";
import type { Trace, Event, Stats, AnalystReport } from "./api";
import { fmtDuration, fmtCost, fmtTime, fmtTokenCount } from "./lib/format";

/* Standardized icon weight across the whole app (see Section 3.C of the taste skill). */
const W = { weight: "bold" as const };

/* Event type -> glyph + rail-color class. Replaces the old emoji map. */
function eventVisual(eventType: string): { Icon: Icon; cls: string } {
  switch (eventType) {
    case "trace.start":
      return { Icon: Play, cls: "" };
    case "trace.end":
      return { Icon: Stop, cls: "" };
    case "llm.call":
      return { Icon: Cpu, cls: "llm" };
    case "tool.call":
      return { Icon: Wrench, cls: "tool" };
    case "reasoning":
      return { Icon: Lightbulb, cls: "reasoning" };
    case "memory.read":
      return { Icon: BookOpen, cls: "" };
    case "memory.write":
      return { Icon: PencilSimple, cls: "" };
    case "decision":
      return { Icon: Path, cls: "" };
    case "error":
      return { Icon: XCircle, cls: "error" };
    case "retry":
      return { Icon: ArrowClockwise, cls: "" };
    case "human.input":
      return { Icon: User, cls: "" };
    default:
      return { Icon: Dot, cls: "" };
  }
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

  const filteredTraces = traces.filter(
    (t) => !search || t.name.toLowerCase().includes(search.toLowerCase())
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
          <div className="brand">
            <Waveform size={22} {...W} />
            <span className="brand-name">VibeTrace</span>
          </div>
          <div className="brand-sub">AI Agent observability</div>
        </div>

        {stats && (
          <div className="sidebar-stats">
            <div className="metric">
              <div className="metric-label">Traces</div>
              <div className="metric-value">{stats.total_traces}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Errors</div>
              <div
                className={`metric-value ${
                  stats.error_traces > 0 ? "danger" : ""
                }`}
              >
                {stats.error_traces}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Tokens</div>
              <div className="metric-value">
                {fmtTokenCount(stats.total_tokens)}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Cost</div>
              <div className="metric-value">{fmtCost(stats.total_cost_usd)}</div>
            </div>
          </div>
        )}

        <div className="sidebar-controls">
          <input
            placeholder="Search traces"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="setup-row">
          <button className="primary" onClick={setupClaudeCode}>
            <Plug size={15} {...W} />
            Setup Claude Code Hooks
          </button>
          {setupStatus && (
            <div className="setup-status">
              <CheckCircle size={13} {...W} />
              {setupStatus}
            </div>
          )}
        </div>

        <div className="trace-list">
          {filteredTraces.length === 0 ? (
            <div className="muted" style={{ padding: 24, textAlign: "center", fontSize: 12 }}>
              No traces yet.
              <br />
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
                  {t.status === "ok" ? (
                    <CheckCircle size={14} {...W} className="status-ok" />
                  ) : (
                    <XCircle size={14} {...W} className="status-error" />
                  )}
                  {t.name}
                </div>
                {t.vibe && (
                  <span className="vibe-badge">
                    <PaintBrush size={11} {...W} />
                    {t.vibe}
                  </span>
                )}
                <div className="trace-meta">
                  <span className="meta-item">
                    <Timer size={12} {...W} />
                    {fmtDuration(t.duration_ms)}
                  </span>
                  <span className="meta-item">
                    <Cpu size={12} {...W} />
                    {t.total_llm_calls}
                  </span>
                  <span className="meta-item">
                    <Wrench size={12} {...W} />
                    {t.total_tool_calls}
                  </span>
                  <span className="meta-item">
                    <Coins size={12} {...W} />
                    {fmtCost(t.total_cost_usd)}
                  </span>
                  <span className="meta-item">
                    <Clock size={12} {...W} />
                    {fmtTime(t.start_time)}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className="main">
        {!selectedTrace ? (
          <div className="empty-state">
            <Waveform size={60} {...W} className="empty-mark" />
            <h2>VibeTrace</h2>
            <p>Calm, insightful, minimalist observability for AI Agents.</p>
            <p className="hint">
              Connect to Claude Code by clicking{" "}
              <strong>"Setup Claude Code Hooks"</strong> on the left. Or run{" "}
              <code>vibetrace demo</code> in your terminal (the Python package)
              to populate traces.
            </p>
          </div>
        ) : (
          <>
            <div className="detail-header">
              <div>
                <div className="detail-title">
                  {selectedTrace.status === "ok" ? (
                    <CheckCircle size={18} {...W} className="status-ok" />
                  ) : (
                    <XCircle size={18} {...W} className="status-error" />
                  )}
                  {selectedTrace.name}
                </div>
                {selectedTrace.vibe && (
                  <span
                    className="vibe-badge"
                    style={{ marginTop: 8, display: "inline-flex" }}
                  >
                    <PaintBrush size={11} {...W} />
                    {selectedTrace.vibe}
                  </span>
                )}
                <div className="detail-stats">
                  <span className="detail-stat">
                    <Timer size={13} {...W} />
                    <strong>{fmtDuration(selectedTrace.duration_ms)}</strong>
                  </span>
                  <span className="detail-stat">
                    <ChartBar size={13} {...W} />
                    <strong>{selectedTrace.total_events}</strong> events
                  </span>
                  <span className="detail-stat">
                    <Cpu size={13} {...W} />
                    <strong>{selectedTrace.total_llm_calls}</strong> LLM
                  </span>
                  <span className="detail-stat">
                    <Wrench size={13} {...W} />
                    <strong>{selectedTrace.total_tool_calls}</strong> tools
                  </span>
                  <span className="detail-stat">
                    <Hash size={13} {...W} />
                    <strong>{fmtTokenCount(selectedTrace.total_tokens)}</strong>{" "}
                    tokens
                  </span>
                  <span className="detail-stat">
                    <Coins size={13} {...W} />
                    <strong>{fmtCost(selectedTrace.total_cost_usd)}</strong>
                  </span>
                </div>
                {selectedTrace.error && (
                  <div className="detail-error">
                    <XCircle size={13} {...W} />
                    {selectedTrace.error}
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
                <Trash size={14} {...W} />
                Delete
              </button>
            </div>

            <div className="tabs">
              <div
                className={`tab ${tab === "timeline" ? "active" : ""}`}
                onClick={() => setTab("timeline")}
              >
                <Timer size={15} {...W} />
                Timeline
              </div>
              <div
                className={`tab ${tab === "graph" ? "active" : ""}`}
                onClick={() => setTab("graph")}
              >
                <TreeStructure size={15} {...W} />
                Graph
              </div>
              <div
                className={`tab ${tab === "analyst" ? "active" : ""}`}
                onClick={() => setTab("analyst")}
              >
                <Brain size={15} {...W} />
                Analyst
              </div>
              <div
                className={`tab ${tab === "vibe" ? "active" : ""}`}
                onClick={() => setTab("vibe")}
              >
                <PaintBrush size={15} {...W} />
                Vibe
              </div>
            </div>

            <div className="tab-content">
              {tab === "timeline" && <TimelineView events={events} />}
              {tab === "graph" && <GraphView events={events} />}
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

function EventGlyph({ eventType, size = 14 }: { eventType: string; size?: number }) {
  const { Icon, cls } = eventVisual(eventType);
  return <Icon size={size} {...W} className={`event-ico ${cls}`} />;
}

function TimelineView({ events }: { events: Event[] }) {
  if (events.length === 0) {
    return <div className="muted">No events.</div>;
  }
  const baseTime = new Date(events[0].start_time).getTime();
  return (
    <div>
      {events.map((e) => {
        const offset = new Date(e.start_time).getTime() - baseTime;
        return (
          <div key={e.event_id} className={`event-card ${eventClass(e)}`}>
            <div className="event-header">
              <EventGlyph eventType={e.event_type} />
              <span className="event-title">{e.event_type}</span>
              <span className="event-name">· {e.name}</span>
              {e.status === "error" && (
                <XCircle size={13} {...W} className="status-error" />
              )}
              <span className="event-time">
                +{offset}ms · {fmtDuration(e.duration_ms)}
              </span>
            </div>
            {(e.model || e.total_tokens || e.cost_usd) && (
              <div className="event-meta">
                {e.model && (
                  <span className="meta-item">
                    <Cpu size={12} {...W} />
                    {e.model}
                  </span>
                )}
                {e.total_tokens && (
                  <span className="meta-item">
                    <Hash size={12} {...W} />
                    {e.total_tokens} tokens
                  </span>
                )}
                {e.cost_usd && (
                  <span className="meta-item">
                    <Coins size={12} {...W} />
                    {fmtCost(e.cost_usd)}
                  </span>
                )}
                {e.tool_name && (
                  <span className="meta-item">
                    <Wrench size={12} {...W} />
                    {e.tool_name}
                  </span>
                )}
              </div>
            )}
            {(e.input || e.output || e.error) && (
              <details className="event-details">
                <summary>Show details</summary>
                {e.input && (
                  <div className="event-detail">
                    <span className="detail-label">Input:</span>{" "}
                    {JSON.stringify(e.input, null, 2).slice(0, 1000)}
                  </div>
                )}
                {e.output && (
                  <div className="event-detail">
                    <span className="detail-label">Output:</span>{" "}
                    {JSON.stringify(e.output, null, 2).slice(0, 1000)}
                  </div>
                )}
                {e.error && (
                  <div className="event-detail is-error">
                    <span className="detail-label">Error:</span> {e.error}
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
    return <div className="muted">No events.</div>;
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
        <div className="graph-node" style={{ paddingLeft: depth * 24 }}>
          <EventGlyph eventType={e.event_type} size={13} />
          <span className="graph-type">{e.event_type}</span>
          <span className="graph-name">· {e.name}</span>
          <span className="graph-dur">{fmtDuration(e.duration_ms)}</span>
        </div>
        {children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };
  return <div>{roots.map((r) => renderNode(r, 0))}</div>;
}

function AnalystView({
  report,
  traceId,
}: {
  report: AnalystReport | null;
  traceId: string;
}) {
  if (!report) {
    return (
      <div className="analyst-loading">
        <Brain size={28} {...W} className="loading-ico" />
        <span>Analyzing trace...</span>
      </div>
    );
  }
  // Render markdown as plain text with simple line-by-line parsing.
  const lines = report.markdown.split("\n");
  return (
    <div className="analyst-report">
      {lines.map((line, i) => {
        if (line.startsWith("# ")) {
          return <h1 key={i}>{line.slice(2)}</h1>;
        }
        if (line.startsWith("## ")) {
          return <h2 key={i}>{line.slice(3)}</h2>;
        }
        if (line.startsWith("> ")) {
          return (
            <div key={i} className="quote">
              {line.slice(2)}
            </div>
          );
        }
        if (line.startsWith("- ")) {
          return (
            <div key={i} className="bullet">
              <span>{line.slice(2)}</span>
            </div>
          );
        }
        if (line.trim() === "") return <br key={i} />;
        return <div key={i}>{line}</div>;
      })}
    </div>
  );
}

function VibeView({ trace, events }: { trace: Trace; events: Event[] }) {
  if (!trace.vibe) {
    return <div className="muted">No vibe set for this trace.</div>;
  }
  const outputs = events
    .filter((e) => e.output)
    .map((e) => JSON.stringify(e.output))
    .join(" ");
  const vl = trace.vibe.toLowerCase();
  const ol = outputs.toLowerCase();
  const findings: string[] = [];
  if (
    (vl.includes("minimalist") || vl.includes("minimal") || vl.includes("简洁")) &&
    outputs.length > 5000
  ) {
    findings.push(
      "Output very long (" + outputs.length + " chars), may violate 'minimalist' vibe"
    );
  }
  if (
    (vl.includes("calm") || vl.includes("平静")) &&
    ["urgent", "panic", "asap", "crash", "崩溃"].some((w) => ol.includes(w))
  ) {
    findings.push("Output contains panic/urgent words, conflicts with 'calm' vibe");
  }
  if (
    (vl.includes("professional") || vl.includes("专业")) &&
    ["lol", "haha", "omg", "嘿嘿"].some((w) => ol.includes(w))
  ) {
    findings.push("Output contains informal words, conflicts with 'professional' vibe");
  }
  return (
    <div className="vibe-view">
      <div className="vibe-origin">
        <div className="vibe-label">Original vibe</div>
        <span className="vibe-badge" style={{ fontSize: 14, padding: "5px 12px" }}>
          <PaintBrush size={12} {...W} />
          {trace.vibe}
        </span>
      </div>
      <div>
        <div className="vibe-heading">Vibe Deviation Check</div>
        {findings.length === 0 ? (
          <div className="vibe-ok">
            <CheckCircle size={15} {...W} />
            No obvious vibe deviation detected.
          </div>
        ) : (
          findings.map((f, i) => (
            <div key={i} className="vibe-finding">
              <Warning size={14} {...W} />
              {f}
            </div>
          ))
        )}
      </div>
      <div className="vibe-note">
        <Info size={14} {...W} />
        <span>
          Vibe Check uses keyword heuristics. For deep LLM-powered analysis, set{" "}
          <code>ANTHROPIC_API_KEY</code> in the Python package and re-run.
        </span>
      </div>
    </div>
  );
}

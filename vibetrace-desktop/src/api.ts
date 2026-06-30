// Tauri commands bindings
import { invoke } from "@tauri-apps/api/core";

export interface Trace {
  trace_id: string;
  name: string;
  vibe: string;
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  input: any;
  output: any;
  status: "ok" | "error" | "timeout" | "cancelled";
  error: string | null;
  total_events: number;
  total_llm_calls: number;
  total_tool_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  error_count: number;
  metadata: Record<string, any>;
  tags: string[];
}

export interface Event {
  event_id: string;
  trace_id: string;
  parent_id: string | null;
  span_id: string;
  event_type: string;
  name: string;
  status: "ok" | "error" | "timeout" | "cancelled";
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  input: any;
  output: any;
  error: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  tool_name: string | null;
  metadata: Record<string, any>;
  tags: string[];
}

export interface Stats {
  total_traces: number;
  error_traces: number;
  total_tokens: number;
  total_cost_usd: number;
  total_llm_calls: number;
  total_tool_calls: number;
  avg_duration_ms: number;
}

export interface PatternFinding {
  kind: string;
  message: string;
  severity: string;
}

export interface AnalystReport {
  trace_id: string;
  summary: string;
  root_cause: string | null;
  patterns: PatternFinding[];
  suggestions: string[];
  vibe_deviation: string[];
  markdown: string;
}

export const listTraces = (limit = 50) => invoke<Trace[]>("list_traces", { limit });
export const getTrace = (traceId: string) => invoke<Trace | null>("get_trace", { traceId });
export const getEvents = (traceId: string) => invoke<Event[]>("get_events", { traceId });
export const getStats = () => invoke<Stats>("get_stats");
export const analyzeTrace = (traceId: string) => invoke<AnalystReport>("analyze_trace", { traceId });
export const deleteTrace = (traceId: string) => invoke<void>("delete_trace", { traceId });
export const initClaudeCodeHooks = (port: number) =>
  invoke<string>("init_claude_code_hooks", { port });

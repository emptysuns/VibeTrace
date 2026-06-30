"""
SQLite 存储后端

设计要点:
- 单文件 DB (./vibetrace.db 默认)
- 两张表: traces (一次运行的元信息), events (所有事件，扁平化)
- JSON 列存 input/output (避免复杂 schema)
- 同步 SQLite (用 sqlite3 stdlib)，足够 MVP

为什么 SQLite:
- 零配置 (无外部依赖)
- 快速 (本地查询 < 10ms for 10k events)
- 容易 backup (单文件)
- 容易 inspect (用 DB Browser for SQLite)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from vibetrace.core.events import EventStatus  # 提前 import 给 helper 用
from pathlib import Path
from typing import List, Optional, Dict, Any

from vibetrace.core.events import Event, Trace


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vibe TEXT DEFAULT '',
    start_time REAL NOT NULL,
    end_time REAL,
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
    metadata TEXT,  -- JSON
    tags TEXT,       -- JSON array
    analyst_report TEXT,  -- AI 分析报告
    analyst_run_at REAL
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
    start_time REAL NOT NULL,
    end_time REAL,
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

-- 关键: 因为 trace 表用 INSERT OR REPLACE 多次 upsert,
-- 而 SQLite 的 INSERT OR REPLACE 等价于 DELETE+INSERT,
-- 会触发 ON DELETE CASCADE 删掉所有 events!
-- 解决: 用 ON UPDATE NO ACTION (默认) + 不删除 trace, 改用 UPDATE
-- 但保留 ON DELETE CASCADE 以支持 delete_trace() 的级联清理

CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id, start_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
"""


def _json_dumps(value: Any) -> str:
    """JSON 序列化，容错处理不可序列化的对象。"""
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(repr(value), ensure_ascii=False)


def _json_loads(s: Optional[str], default):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


class SQLiteStore:
    """
    SQLite 存储后端。

    Thread-safe (用 lock 序列化写操作)。
    """

    def __init__(self, db_path: str = "./vibetrace.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # 关键修复: 用 timeout 处理并发，busy_timeout 避免短时锁竞争
        # 同时连接应该 per-thread
        self._init_lock = threading.Lock()
        self._local = threading.local()  # 每个 thread 一个 connection
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """获取 thread-local connection。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            # 关键: timeout=30 让 SQLite 等待锁释放，而不是立即报 locked
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            # WAL 模式: 写不阻塞读, 写完后 checkpoint 让其他 connection 可见
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            # 5 秒 busy timeout
            conn.execute("PRAGMA busy_timeout=5000")
            # synchronous=NORMAL: 平衡性能与持久性
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _force_checkpoint(self):
        """强制 WAL checkpoint, 让其他 connection 看到写入的数据。"""
        try:
            conn = self._get_conn()
            # FULL 确保所有 commit 数据落盘
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        except Exception:
            pass

    def _init_schema(self):
        with self._init_lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            conn.commit()

    def _execute_with_retry(self, fn, max_retries=3):
        """执行 SQL, 在 database is locked 时短暂重试."""
        import time as _time
        last_err = None
        for attempt in range(max_retries):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    _time.sleep(0.01 * (attempt + 1))
                    last_err = e
                    continue
                raise
        if last_err:
            raise last_err

    def save_event(self, event: Event) -> None:
        """保存一个 event。"""
        conn = self._get_conn()
        def _do():
            # 关键: 不能用 INSERT OR REPLACE 在 events 表里 (虽然 event_id 是 PK,
            # 但如果有 trace_id FK 链, 仍要小心)
            existing = conn.execute(
                "SELECT 1 FROM events WHERE event_id = ?", (event.event_id,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE events SET
                        trace_id = ?, parent_id = ?, span_id = ?, event_type = ?,
                        name = ?, status = ?, start_time = ?, end_time = ?, duration_ms = ?,
                        input = ?, output = ?, error = ?,
                        model = ?, prompt_tokens = ?, completion_tokens = ?, total_tokens = ?,
                        cost_usd = ?, tool_name = ?, metadata = ?, tags = ?
                    WHERE event_id = ?
                    """,
                    (
                        event.trace_id, event.parent_id, event.span_id, event.event_type.value,
                        event.name, event.status.value, event.start_time, event.end_time, event.duration_ms,
                        _json_dumps(event.input), _json_dumps(event.output), event.error,
                        event.model, event.prompt_tokens, event.completion_tokens, event.total_tokens,
                        event.cost_usd, event.tool_name, _json_dumps(event.metadata), _json_dumps(event.tags),
                        event.event_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO events (
                        event_id, trace_id, parent_id, span_id, event_type, name, status,
                        start_time, end_time, duration_ms,
                        input, output, error,
                        model, prompt_tokens, completion_tokens, total_tokens, cost_usd,
                        tool_name, metadata, tags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.trace_id,
                        event.parent_id,
                        event.span_id,
                        event.event_type.value,
                        event.name,
                        event.status.value,
                        event.start_time,
                        event.end_time,
                        event.duration_ms,
                        _json_dumps(event.input),
                        _json_dumps(event.output),
                        event.error,
                        event.model,
                        event.prompt_tokens,
                        event.completion_tokens,
                        event.total_tokens,
                        event.cost_usd,
                        event.tool_name,
                        _json_dumps(event.metadata),
                        _json_dumps(event.tags),
                    ),
                )
            conn.commit()
        self._execute_with_retry(_do)

    def save_trace(self, trace: Trace, events: Optional[List[Event]] = None) -> None:
        """保存 trace 元信息 (events 单独保存)。"""
        conn = self._get_conn()
        def _do():
            # 关键: 不能用 INSERT OR REPLACE 因为它等价于 DELETE+INSERT,
            # 在 FK 启用时会触发 ON DELETE CASCADE 删掉所有 events!
            # 改用 "先查再决定 INSERT 还是 UPDATE" 模式
            existing = conn.execute(
                "SELECT 1 FROM traces WHERE trace_id = ?", (trace.trace_id,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE traces SET
                        name = ?, vibe = ?, start_time = ?, end_time = ?, duration_ms = ?,
                        status = ?, error = ?, input = ?, output = ?,
                        total_events = ?, total_llm_calls = ?, total_tool_calls = ?,
                        total_tokens = ?, total_cost_usd = ?, error_count = ?,
                        metadata = ?, tags = ?
                    WHERE trace_id = ?
                    """,
                    (
                        trace.name, trace.vibe, trace.start_time, trace.end_time, trace.duration_ms,
                        trace.status.value, trace.error, _json_dumps(trace.input), _json_dumps(trace.output),
                        trace.total_events, trace.total_llm_calls, trace.total_tool_calls,
                        trace.total_tokens, trace.total_cost_usd, trace.error_count,
                        _json_dumps(trace.metadata), _json_dumps(trace.tags),
                        trace.trace_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO traces (
                        trace_id, name, vibe, start_time, end_time, duration_ms,
                        status, error, input, output,
                        total_events, total_llm_calls, total_tool_calls, total_tokens,
                        total_cost_usd, error_count, metadata, tags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
                        trace.name,
                        trace.vibe,
                        trace.start_time,
                        trace.end_time,
                        trace.duration_ms,
                        trace.status.value,
                        trace.error,
                        _json_dumps(trace.input),
                        _json_dumps(trace.output),
                        trace.total_events,
                        trace.total_llm_calls,
                        trace.total_tool_calls,
                        trace.total_tokens,
                        trace.total_cost_usd,
                        trace.error_count,
                        _json_dumps(trace.metadata),
                        _json_dumps(trace.tags),
                    ),
                )
            conn.commit()
        self._execute_with_retry(_do)

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """获取 trace 元信息。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_trace(row)

    def get_events(self, trace_id: str) -> List[Event]:
        """获取一个 trace 的所有 events，按时间排序。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE trace_id = ? ORDER BY start_time ASC, event_id ASC",
            (trace_id,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_trace_with_events(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """一次获取 trace + events。"""
        trace = self.get_trace(trace_id)
        if trace is None:
            return None
        events = self.get_events(trace_id)
        return {"trace": trace, "events": events}

    def list_traces(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        name_contains: Optional[str] = None,
    ) -> List[Trace]:
        """列出 traces，按时间倒序。"""
        conn = self._get_conn()
        sql = "SELECT * FROM traces WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if name_contains:
            sql += " AND name LIKE ?"
            params.append(f"%{name_contains}%")
        sql += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def count_traces(self, status: Optional[str] = None) -> int:
        conn = self._get_conn()
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM traces WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM traces").fetchone()
        return row["c"]

    def get_stats(self) -> Dict[str, Any]:
        """全局统计。"""
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_traces,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_traces,
                SUM(total_tokens) as total_tokens,
                SUM(total_cost_usd) as total_cost,
                SUM(total_llm_calls) as total_llm_calls,
                SUM(total_tool_calls) as total_tool_calls,
                AVG(duration_ms) as avg_duration_ms
            FROM traces
            """
        ).fetchone()
        return {
            "total_traces": row["total_traces"] or 0,
            "error_traces": row["error_traces"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "total_cost_usd": row["total_cost"] or 0.0,
            "total_llm_calls": row["total_llm_calls"] or 0,
            "total_tool_calls": row["total_tool_calls"] or 0,
            "avg_duration_ms": row["avg_duration_ms"] or 0.0,
        }

    def save_analyst_report(self, trace_id: str, report: str) -> None:
        """保存 AI Analyst 报告。"""
        conn = self._get_conn()
        def _do():
            conn.execute(
                "UPDATE traces SET analyst_report = ?, analyst_run_at = ? WHERE trace_id = ?",
                (report, time.time(), trace_id),
            )
            conn.commit()
        self._execute_with_retry(_do)

    def get_analyst_report(self, trace_id: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT analyst_report FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        return row["analyst_report"] if row else None

    def delete_trace(self, trace_id: str) -> None:
        conn = self._get_conn()
        def _do():
            conn.execute("DELETE FROM events WHERE trace_id = ?", (trace_id,))
            conn.execute("DELETE FROM traces WHERE trace_id = ?", (trace_id,))
            conn.commit()
        self._execute_with_retry(_do)

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # === Helpers ===

    def _row_to_trace(self, row: sqlite3.Row) -> Trace:
        return Trace(
            trace_id=row["trace_id"],
            name=row["name"],
            vibe=row["vibe"] or "",
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_ms=row["duration_ms"],
            status=EventStatus(row["status"] or "ok"),
            error=row["error"],
            input=_json_loads(row["input"], None),
            output=_json_loads(row["output"], None),
            total_events=row["total_events"] or 0,
            total_llm_calls=row["total_llm_calls"] or 0,
            total_tool_calls=row["total_tool_calls"] or 0,
            total_tokens=row["total_tokens"] or 0,
            total_cost_usd=row["total_cost_usd"] or 0.0,
            error_count=row["error_count"] or 0,
            metadata=_json_loads(row["metadata"], {}),
            tags=_json_loads(row["tags"], []),
        )

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        from vibetrace.core.events import EventType, EventStatus
        return Event(
            event_id=row["event_id"],
            trace_id=row["trace_id"],
            parent_id=row["parent_id"],
            span_id=row["span_id"],
            event_type=EventType(row["event_type"]),
            name=row["name"] or "",
            status=EventStatus(row["status"] or "ok"),
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_ms=row["duration_ms"],
            input=_json_loads(row["input"], None),
            output=_json_loads(row["output"], None),
            error=row["error"],
            model=row["model"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"],
            cost_usd=row["cost_usd"],
            tool_name=row["tool_name"],
            metadata=_json_loads(row["metadata"], {}),
            tags=_json_loads(row["tags"], []),
        )

"""最小表集建表（M0）。

依据：docs/11 §3.3「最小表集」，字段来源：
  memory_item          -> docs/02 §4.1
  memory_edge          -> docs/02 §4.2
  memory_access_log    -> docs/02 §4.2
  message_log          -> docs/03 §10
  skill_call_log       -> docs/03 §10
  task / task_step     -> docs/05 §4
  trace_snapshot       -> docs/03 §10
  plan_record / replan_record / plan_rejection -> docs/09 §8.2

技术：SQLAlchemy 2.x（屏蔽方言差异，docs/07 §2）。默认 SQLite；
`create_engine_for(url)` 支持 `sqlite:///:memory:` 与临时文件。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

# --------------------------------------------------------------------- 任务
task_table = Table(
    "task",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("trigger", String(16), nullable=False),
    Column("trigger_ref", String(128)),
    Column("scope", JSON, nullable=False),
    Column("intent", String(32), nullable=False),
    Column("params", JSON),
    Column("depth", String(4), nullable=False),
    Column("priority", String(16), nullable=False),
    Column("budget", JSON, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("constraints", JSON),
    Column("status", String(16), nullable=False),
    Column("created_at", String(40)),
)

task_step_table = Table(
    "task_step",
    metadata,
    Column("step_id", String(64), primary_key=True),
    Column("task_id", String(64), nullable=False, index=True),
    Column("node_id", String(64), nullable=False),
    Column("capability", String(64), nullable=False),
    Column("agent_id", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempt", Integer, default=1),
    Column("message_id", String(64)),
    Column("started_at", String(40)),
    Column("ended_at", String(40)),
)

# --------------------------------------------------------------------- 记忆
memory_item_table = Table(
    "memory_item",
    metadata,
    Column("memory_id", String(64), primary_key=True),
    Column("scope_type", String(16), nullable=False, index=True),
    Column("scope_id", String(64), index=True),
    Column("mem_type", String(32), nullable=False, index=True),
    Column("title", String(120), nullable=False),
    Column("content", Text, nullable=False),
    Column("structured_payload", JSON),
    Column("source_type", String(32), nullable=False),
    Column("source_ref", String(128), nullable=False),          # 硬约束：必填
    Column("confidence", Float, nullable=False),
    Column("importance", Float, default=0.5),
    Column("access_count", Integer, default=0),
    Column("last_access_at", String(40)),
    Column("decay_score", Float, default=1.0),
    Column("valid_from", String(40)),
    Column("valid_until", String(40)),
    Column("status", String(16), nullable=False, index=True),
    Column("sensitivity_level", String(16), default="internal"),
    Column("owner_user_id", String(64), index=True),
    Column("tags", JSON),
    Column("embedding_ref", String(128)),
    Column("created_at", String(40)),
)

memory_edge_table = Table(
    "memory_edge",
    metadata,
    Column("edge_id", String(64), primary_key=True),
    Column("from_memory_id", String(64), nullable=False, index=True),
    Column("to_memory_id", String(64), nullable=False, index=True),
    Column("edge_type", String(24), nullable=False),
    Column("weight", Float, default=1.0),
    Column("reason", Text),
    Column("created_at", String(40)),
)

memory_access_log_table = Table(
    "memory_access_log",
    metadata,
    Column("access_id", String(64), primary_key=True),
    Column("memory_id", String(64), nullable=False, index=True),
    Column("query", Text),
    Column("caller", String(64)),
    Column("scores", JSON),
    Column("latency_ms", Integer, default=0),
    Column("used_in_output", Boolean, default=False),   # T-4 回填（docs/10 §6）
    Column("accessed_at", String(40)),
)

# --------------------------------------------------------------------- 通信
message_log_table = Table(
    "message_log",
    metadata,
    Column("msg_id", String(64), primary_key=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("parent_msg_id", String(64), index=True),    # 因果树重建的依据
    Column("session_id", String(64)),
    Column("task_id", String(64), index=True),
    Column("seq", Integer, default=0),
    Column("sender", String(64), nullable=False),
    Column("receiver", String(64), nullable=False),
    Column("performative", String(16), nullable=False),
    Column("intent", String(64)),
    Column("payload_digest", String(64)),
    Column("context_memory_ids", JSON),
    Column("context_skill_calls", JSON),
    Column("status", String(16)),
    Column("confidence", Float),
    Column("model_name", String(64)),
    Column("model_profile", String(32)),
    Column("prompt_tokens", Integer, default=0),
    Column("completion_tokens", Integer, default=0),
    Column("latency_ms", Integer, default=0),
    Column("security_role", String(32)),
    Column("timestamp", String(40), index=True),
)

skill_call_log_table = Table(
    "skill_call_log",
    metadata,
    Column("call_id", String(64), primary_key=True),
    Column("trace_id", String(64), index=True),
    Column("msg_id", String(64)),
    Column("skill_id", String(64), nullable=False, index=True),
    Column("skill_version", String(16)),
    Column("caller_agent", String(64), nullable=False),
    Column("input_digest", String(64)),
    Column("output_digest", String(64)),
    Column("cache_hit", Boolean, default=False),
    Column("fallback_level", String(4), default="L0"),
    Column("latency_ms", Integer, default=0),
    Column("status", String(16)),
    Column("created_at", String(40)),
)

# --------------------------------------------------------------------- 审计
trace_snapshot_table = Table(
    "trace_snapshot",
    metadata,
    Column("snapshot_id", String(64), primary_key=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("task_type", String(64)),
    Column("started_at", String(40)),
    Column("ended_at", String(40)),
    Column("total_ms", Integer, default=0),
    Column("message_seq", JSON),
    Column("final_result", JSON),
    Column("key_metrics", JSON),
)

# --------------------------------------------------------------------- 规划
plan_record_table = Table(
    "plan_record",
    metadata,
    Column("plan_id", String(64), primary_key=True),
    Column("task_id", String(64), nullable=False, index=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("intent", String(32), nullable=False),
    Column("depth", String(4), nullable=False),
    Column("scope_summary", JSON),
    Column("selected_agents", JSON),
    Column("graph", JSON, nullable=False),
    Column("rationale", JSON),
    Column("created_at", String(40)),
)

replan_record_table = Table(
    "replan_record",
    metadata,
    Column("replan_id", String(64), primary_key=True),
    Column("task_id", String(64), nullable=False, index=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("trigger", JSON, nullable=False),
    Column("impact_scope", JSON),
    Column("replacement", JSON),
    Column("graph_before", JSON),
    Column("graph_after", JSON),
    Column("attempt", Integer, default=1),
    Column("resolved", Boolean, default=False),
    Column("created_at", String(40)),
)

plan_rejection_table = Table(
    "plan_rejection",
    metadata,
    Column("rejection_id", String(64), primary_key=True),
    Column("task_id", String(64), index=True),
    Column("trace_id", String(64), index=True),
    Column("reason", String(48), nullable=False),
    Column("detail", Text),
    Column("offending_refs", JSON),
    Column("at_step", String(32)),
    Column("created_at", String(40)),
)


#: M0 最小表集清单（docs/11 §3.3）
TABLES: tuple[Table, ...] = (
    task_table,
    task_step_table,
    memory_item_table,
    memory_edge_table,
    memory_access_log_table,
    message_log_table,
    skill_call_log_table,
    trace_snapshot_table,
    plan_record_table,
    replan_record_table,
    plan_rejection_table,
)


def create_engine_for(url: str = "sqlite:///:memory:", **kwargs: Any) -> Engine:
    """建立引擎。默认 SQLite 内存库（docs/11 §3.5 允许）。"""
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, future=True, connect_args=connect_args, **kwargs)


def create_all(engine: Engine) -> list[str]:
    """建表并返回已创建的表名。"""
    metadata.create_all(engine)
    return [t.name for t in TABLES]

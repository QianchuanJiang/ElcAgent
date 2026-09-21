"""契约层枚举：受控词表。

设计依据：
  - 意图枚举      -> docs/09 §3.1
  - 言语行为      -> docs/03 §4
  - 执行深度      -> docs/08 §4.1
  - 记忆类型      -> docs/02 §2
  - 作用域        -> docs/02 §4.1
  - 实现模式/审计 -> docs/04 §2
  - 模型档位      -> docs/07 §1.1、docs/01 §3
  - 权限岗位      -> docs/01 §3、docs/04 §2

约定：意图与言语行为是**受控词表**，不允许自由文本，因为它们充当路由键。
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """字符串枚举基类，便于直接参与 JSON 序列化与比较。"""

    def __str__(self) -> str:  # pragma: no cover - 仅用于展示
        return self.value


# --------------------------------------------------------------------------
# 意图（docs/09 §3.1）
# --------------------------------------------------------------------------
class Intent(StrEnum):
    RISK_ASSESSMENT = "risk_assessment"
    POINT_QUERY = "point_query"
    ROOT_CAUSE = "root_cause"
    PLAN_SOLVE = "plan_solve"
    BRIEF_GENERATE = "brief_generate"
    DATA_CHECK = "data_check"
    CONFIG_UPDATE = "config_update"


# --------------------------------------------------------------------------
# 言语行为（docs/03 §4）
# --------------------------------------------------------------------------
class Performative(StrEnum):
    REQUEST = "REQUEST"
    DELEGATE = "DELEGATE"
    QUERY = "QUERY"
    INFORM = "INFORM"
    PROPOSE = "PROPOSE"
    ACCEPT = "ACCEPT"
    REFUSE = "REFUSE"
    CONFIRM = "CONFIRM"
    FAILURE = "FAILURE"
    ESCALATE = "ESCALATE"


#: 每个 performative 的确定响应集合（docs/03 §4「协议纪律」）。
#: REQUEST / DELEGATE / QUERY 均要求"请求类"的响应；INFORM 为通知无返回值。
PERFORMATIVE_RESPONSES: dict[Performative, frozenset[Performative]] = {
    Performative.REQUEST: frozenset(
        {Performative.CONFIRM, Performative.FAILURE, Performative.REFUSE}
    ),
    Performative.DELEGATE: frozenset(
        {Performative.CONFIRM, Performative.FAILURE, Performative.REFUSE}
    ),
    Performative.QUERY: frozenset(
        {Performative.INFORM, Performative.FAILURE, Performative.REFUSE}
    ),
    Performative.PROPOSE: frozenset(
        {
            Performative.ACCEPT,
            Performative.REFUSE,
            Performative.FAILURE,
        }
    ),
    Performative.INFORM: frozenset(),
    Performative.ACCEPT: frozenset(),
    Performative.REFUSE: frozenset(),
    Performative.CONFIRM: frozenset(),
    Performative.FAILURE: frozenset(),
    Performative.ESCALATE: frozenset(),
}


# --------------------------------------------------------------------------
# 执行深度（docs/08 §4.1）
# --------------------------------------------------------------------------
class Depth(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"

    @property
    def level(self) -> int:
        return {"L0": 0, "L1": 1, "L2": 2}[self.value]


# --------------------------------------------------------------------------
# 任务触发源（docs/08 §3.1、§3.3）
# --------------------------------------------------------------------------
class Trigger(StrEnum):
    EVENT = "event"
    SCHEDULE = "schedule"
    USER = "user"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


# --------------------------------------------------------------------------
# 记忆（docs/02 §2、§4.1）
# --------------------------------------------------------------------------
class MemoryType(StrEnum):
    # 短期
    SESSION_BUFFER = "session_buffer"          # 会话缓冲
    TASK_WORKING = "task_working"              # 任务工作记忆
    ROLLING_SUMMARY = "rolling_summary"        # 滚动摘要
    # 长期
    SEMANTIC = "semantic"                      # 语义记忆
    EPISODIC = "episodic"                      # 情节记忆
    PROCEDURAL = "procedural"                  # 程序记忆
    REFLECTIVE = "reflective"                  # 反思记忆
    # 用户
    USER_PROFILE = "user_profile"              # 画像
    USER_PREFERENCE = "user_preference"        # 偏好
    USER_BEHAVIOR = "user_behavior"            # 行为


class MemoryScope(StrEnum):
    SESSION = "session"
    GLOBAL = "global"
    USER = "user"
    ORG = "org"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class MemoryEdgeType(StrEnum):
    DERIVED_FROM = "derived_from"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    RELATED = "related"
    SUPPORTS = "supports"


class RetrievalMode(StrEnum):
    """记忆检索模式（docs/02 §6 统一约束）。"""

    HYBRID = "hybrid"
    DEGRADED = "degraded"


# --------------------------------------------------------------------------
# 技能（docs/04 §2）
# --------------------------------------------------------------------------
class ImplMode(StrEnum):
    RULE = "rule"
    FORMULA = "formula"
    QUERY = "query"
    MODEL = "model"
    TEMPLATE = "template"


class AuditLevel(StrEnum):
    NONE = "none"
    SUMMARY = "summary"
    FULL = "full"


class FallbackLevel(StrEnum):
    """四级降级链层级（docs/04 §2.2 / docs/03 §7.3）。"""

    NORMAL = "L0"          # 第 0 级 正常执行
    CACHE_HIT = "L1"       # 第 1 级 结果缓存命中
    SIMPLIFIED = "L2"      # 第 2 级 简化算法替代
    DEFAULT_VALUE = "L3"   # 第 3 级 返回默认值（占位数据）
    FAILURE = "L4"         # 第 4 级 返回 FAILURE


# --------------------------------------------------------------------------
# 能力模板模式（docs/09 §4.2）
# --------------------------------------------------------------------------
class RequirementMode(StrEnum):
    REQUIRED = "required"
    CONDITIONAL = "conditional"
    OPTIONAL = "optional"


# --------------------------------------------------------------------------
# 智能体（docs/01 §3）
# --------------------------------------------------------------------------
class ModelBinding(StrEnum):
    HEAVY = "heavy"
    LIGHT = "light"
    VISION = "vision"
    EMBED = "embed"
    NONE = "none"


class PermissionScope(StrEnum):
    """最低岗位要求；数值越大权限越高（docs/01 §3）。"""

    OPERATOR = "operator"
    SPECIALIST = "specialist"
    SAFETY = "safety"
    ADMIN = "admin"

    @property
    def level(self) -> int:
        return {"operator": 0, "specialist": 1, "safety": 2, "admin": 3}[self.value]


class AgentStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


# --------------------------------------------------------------------------
# 消息与任务状态
# --------------------------------------------------------------------------
class ResultStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    REFUSED = "refused"


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class ReceiverType(StrEnum):
    AGENT = "agent"
    SKILL = "skill"
    BROADCAST = "broadcast"
    HUMAN = "human"


class PlanRejectionReason(StrEnum):
    """契约校验器拒绝原因（docs/09 §7 八条铁律）。"""

    UNKNOWN_REFERENCE = "unknown_reference"
    MISSING_REQUIRED_CAPABILITY = "missing_required_capability"
    DEPENDENCY_CYCLE = "dependency_cycle"
    INPUT_NOT_REACHABLE = "input_not_reachable"
    PERMISSION_EXCEEDED = "permission_exceeded"
    DEPTH_EXCEEDED = "depth_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    TERMINAL_OUTPUT_MISMATCH = "terminal_output_mismatch"

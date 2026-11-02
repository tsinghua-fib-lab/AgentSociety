"""跨 step TODO 状态管理（已移入 ``agent.base`` 包）。

本模块只负责 TODO List 的本地状态文件、schema 校验和基础读写操作。
它不直接调用环境模块，也不负责生成日程节律；这些策略由上层 agent 决定。

Moved verbatim from the former ``agentsociety2/agent/todo_state.py``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TODO_STATE_PATH = "TODO.json"
TODO_ARCHIVE_PATH = "state/todos_archive.jsonl"
TodoStatus = Literal["pending", "active", "done", "deferred", "blocked", "cancelled"]
TODO_STATUSES = {"pending", "active", "done", "deferred", "blocked", "cancelled"}
# 「已结束」的 TODO：归档机制只作用于这两种状态，绝不触碰仍在进行或仍可执行的
# pending/active/deferred/blocked。
TERMINAL_TODO_STATUSES = {"done", "cancelled"}
# 自动归档软上限：每次 save 时主列表中已结束 TODO 超过该数量，则把最旧的归档，
# 保证主列表不无限堆积；旧记录进入 todos_archive.jsonl，不丢失。
MAX_TERMINAL_TODOS = 8


def _now_iso() -> str:
    """返回当前本地时间的 ISO 字符串，用于 updated_at 和默认 id。"""
    return datetime.now().isoformat()


def _parse_time(value: Any) -> datetime | None:
    """宽松解析 ISO 时间字符串。

    :param value: 可能来自 JSON 的 due 字段值。
    :returns: 能解析时返回 datetime；为空或格式非法时返回 None。

    .. note::

        这里用于 prompt 摘要排序，必须容忍旧状态文件或外部 seed 中的脏数据。
        严格写入校验由 TodoItem 的 Pydantic validator 完成。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _make_id(existing: set[str]) -> str:
    """生成全局唯一的 TODO id（UUID）。

    :param existing: 当前状态中已经占用的 TODO id 集合（仅作防御性冲突检查）。
    :returns: 形如 ``todo_<uuid hex>`` 的 id；UUID 保证跨归档也不复用，因此不再
        依赖 id 字典序推断创建顺序（归档改用列表位置，见 ``_archive_terminal``）。
    """
    candidate = f"todo_{uuid.uuid4().hex}"
    while candidate in existing:  # 实践中不可能命中；纯防御。
        candidate = f"todo_{uuid.uuid4().hex}"
    return candidate


class TodoItem(BaseModel):
    """单条 TODO 的权威 Pydantic schema。

    :param id: TODO 唯一标识。为空或冲突时由 normalize_todo / TodoState 补齐。
    :param title: 非空标题，是 agent 和 prompt 中展示任务的主要文本。
    :param kind: 任务类型；不限制枚举，推荐 work/meal/sleep/commute/social/leisure/custom。
    :param status: 固定生命周期状态，只允许 TodoStatus 中的值。
    :param priority: 0.0-1.0 的优先级，越大越重要。
    :param due: ISO datetime 字符串或 None；用于到期判断和 prompt 摘要排序。
    :param duration_min: 预计持续分钟数，必须非负；未知时为 None。
    :param recurrence: 重复规则文本；当前只保存，不自动展开实例。
    :param created_by: 来源标识，例如 agent/system/seed/tool。
    :param blocking_reason: blocked/deferred 的原因说明。
    :param notes: 任务备注或完成结果。
    :param metadata: 唯一扩展字段；地点、AOI/POI、环境模块参数都放这里。
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    kind: str = "custom"
    status: TodoStatus = "pending"
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    due: str | None = None
    duration_min: float | None = Field(default=None, ge=0.0)
    recurrence: str | None = None
    created_by: str = "agent"
    blocking_reason: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "id",
        "title",
        "kind",
        "status",
        "due",
        "recurrence",
        "created_by",
        "blocking_reason",
        "notes",
        mode="before",
    )
    @classmethod
    def _stringify_optional_text(cls, value: Any) -> Any:
        """把 JSON 输入中的文本字段统一成去空白字符串。"""
        if value is None:
            return None
        return str(value).strip()

    @field_validator("kind", mode="after")
    @classmethod
    def _default_kind(cls, value: str) -> str:
        """kind 为空时回落到 custom，避免 prompt 里出现空类型。"""
        return value or "custom"

    @field_validator("created_by", mode="after")
    @classmethod
    def _default_created_by(cls, value: str) -> str:
        """created_by 为空时回落到 agent。"""
        return value or "agent"

    @field_validator("title", mode="after")
    @classmethod
    def _non_empty_title(cls, value: str) -> str:
        """title 是核心字段，不能被空字符串写入状态文件。"""
        if not value:
            raise ValueError("todo title must be non-empty")
        return value

    @field_validator("due", "recurrence", "blocking_reason", mode="after")
    @classmethod
    def _empty_string_to_none(cls, value: str | None) -> str | None:
        """把可选文本字段中的空字符串归一化为 None。"""
        return value or None

    @field_validator("due", mode="after")
    @classmethod
    def _valid_due_iso(cls, value: str | None) -> str | None:
        """写入时强制 due 使用 ISO datetime 或 None。"""
        if value is None:
            return None
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("todo due must be an ISO datetime string or null") from exc
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_object(cls, value: Any) -> dict[str, Any]:
        """metadata 必须是 object；非法输入归一化为空扩展对象。"""
        return value if isinstance(value, dict) else {}

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_default(cls, value: Any) -> float:
        """priority 支持字符串数字输入，并裁剪到 0.0-1.0。"""
        if value in (None, ""):
            return 0.5
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, number))

    @field_validator("duration_min", mode="before")
    @classmethod
    def _duration_default(cls, value: Any) -> float | None:
        """duration_min 支持字符串数字输入，空或非法时视为未知。"""
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class TodoState(BaseModel):
    """持久化 TODO 状态文件的 Pydantic schema。

    :param todos: 全量 TODO 列表。
    :param active_todo_id: 当前正在执行的 TODO id；同一时间最多一个。
    :param updated_at: 最近一次保存状态的 ISO 时间。
    """

    model_config = ConfigDict(extra="ignore")

    todos: list[TodoItem] = Field(default_factory=list)
    active_todo_id: str | None = None
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("active_todo_id", mode="before")
    @classmethod
    def _normalize_active_id(cls, value: Any) -> str | None:
        """active_todo_id 为空字符串时归一化为 None。"""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("updated_at", mode="before")
    @classmethod
    def _normalize_updated_at(cls, value: Any) -> str:
        """updated_at 缺失时使用当前时间补齐。"""
        text = str(value or "").strip()
        return text or _now_iso()

    @model_validator(mode="after")
    def _enforce_unique_ids_and_active(self) -> TodoState:
        """状态级约束：TODO id 唯一，且最多只有一个 active。

        规则：
            1. 缺失或重复 id 会被替换成自动生成 id。
            2. active_todo_id 指向的 TODO 会被强制设为 active。
            3. 如果多个 TODO 标记为 active，只保留第一个，其余回落为 pending。
            4. active_todo_id 指向不存在时会被清空。
        """
        used: set[str] = set()
        normalized: list[TodoItem] = []
        for item in self.todos:
            data = item.model_dump(mode="json")
            if not data["id"] or data["id"] in used:
                data["id"] = _make_id(used)
            used.add(data["id"])
            normalized.append(TodoItem.model_validate(data))
        self.todos = normalized

        active_id = self.active_todo_id
        active_exists = False
        for item in self.todos:
            if active_id and item.id == active_id:
                item.status = "active"
                active_exists = True
            elif item.status == "active":
                if active_id is None:
                    active_id = item.id
                    active_exists = True
                else:
                    item.status = "pending"
        if active_id and not active_exists:
            active_id = None
        self.active_todo_id = active_id
        return self


def normalize_todo(
    raw: dict[str, Any], *, existing_ids: set[str] | None = None
) -> dict[str, Any]:
    """把一条原始 TODO 数据归一化为可持久化的公开 schema。

    :param raw: 来自工具调用、seed 文件或已有状态的 TODO dict。
    :param existing_ids: 已存在的 TODO id 集合；用于检测 id 冲突。
    :returns: 已经过 Pydantic 校验、可 JSON 序列化的 TODO dict。
    :raises pydantic.ValidationError: 字段不满足核心 schema 时抛出，例如非法 status/due。
    """
    used = existing_ids or set()
    todo = TodoItem.model_validate(raw if isinstance(raw, dict) else {})
    data = todo.model_dump(mode="json")
    if not data["id"] or data["id"] in used:
        data["id"] = _make_id(used)
    return TodoItem.model_validate(data).model_dump(mode="json")


def normalize_state(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """把原始状态文件内容归一化为可持久化状态。

    :param raw: 原始状态 dict；None 表示创建空状态。
    :returns: 已经过 Pydantic 校验、可 JSON 序列化的状态 dict。
    :raises pydantic.ValidationError: TODO 条目不满足核心 schema 时抛出。
    """
    state = TodoState.model_validate(raw if isinstance(raw, dict) else {})
    return state.model_dump(mode="json")


@dataclass
class TodoStateStore:
    """agent workspace 中 TODO 状态文件的读写门面。

    :param workspace_root: 单个 agent 的 workspace 根目录。

    .. note::

        所有公开 mutation 方法都会先 load，再通过 Pydantic 归一化，
        最后写回 ``state/todos.json``。外部调用者不应绕过 Store 直接改文件。
    """

    workspace_root: Path

    @property
    def path(self) -> Path:
        """TODO 状态文件的绝对路径。"""
        return self.workspace_root / TODO_STATE_PATH

    @property
    def archive_path(self) -> Path:
        """已结束 TODO 的归档文件绝对路径（append-only JSONL）。"""
        return self.workspace_root / TODO_ARCHIVE_PATH

    def exists(self) -> bool:
        """检查 TODO 状态文件是否已经存在。"""
        return self.path.exists()

    def ensure(self) -> dict[str, Any]:
        """确保状态文件存在，并返回归一化后的状态。

        :returns: 当前 TODO 状态。若文件不存在，会创建空状态；若文件存在，会保留
            seed 内容并写回一次归一化结果。
        """
        if not self.exists():
            state = normalize_state()
            self.save(state)
            return state
        state = self.load()
        self.save(state)
        return state

    def load(self) -> dict[str, Any]:
        """读取并归一化 TODO 状态。

        :returns: 归一化后的状态 dict。文件不存在时返回空状态。

        .. note::

            文件缺失、JSON 损坏或顶层不是 object 时，会按空状态处理。
            具体 TODO 字段仍由 Pydantic schema 负责校验。
        """
        if not self.exists():
            return normalize_state()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        return normalize_state(raw if isinstance(raw, dict) else {})

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        """保存 TODO 状态。

        :param state: 待保存的状态 dict。
        :returns: 写入磁盘后的归一化状态 dict。

        .. note::

            写盘前会对「已结束」TODO（done/cancelled）做自动归档：主列表中超过
            ``MAX_TERMINAL_TODOS`` 条的旧记录会追加写入 ``todos_archive.jsonl``
            并从主列表移除，保证主列表不无限堆积；归档不丢失数据。pending/
            active/deferred/blocked 一律不动。
        """
        normalized = normalize_state({**state, "updated_at": _now_iso()})
        archived = self._archive_terminal(normalized, max_keep=MAX_TERMINAL_TODOS)
        if archived:
            self._append_archive(archived)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized

    def _append_archive(self, records: list[dict[str, Any]]) -> None:
        """把待归档的 TODO 记录追加写入归档 JSONL。

        :param records: 已从主列表移除的「已结束」TODO dict 列表。
        :returns: 无返回值。
        """
        if not records:
            return
        stamp = _now_iso()
        self.archive_path.parent.mkdir(parents=True, exist_ok=True)
        with self.archive_path.open("a", encoding="utf-8") as fh:
            for record in records:
                payload = {**record, "archived_at": stamp}
                fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _archive_terminal(
        self,
        state: dict[str, Any],
        *,
        max_keep: int,
    ) -> list[dict[str, Any]]:
        """把超量的「已结束」TODO 从主列表移除并返回待归档记录。

        只作用于 status ∈ {done, cancelled} 的项；保留列表中**位置最靠后**（即
        最近创建/完成）的 ``max_keep`` 条，更早的移出 ``state["todos"]``。id 现为
        UUID、不再带时间序，故一律按列表位置判定新旧。

        :param state: 被 mutate 的状态 dict（就地修改 todos 列表）。
        :param max_keep: 主列表中保留的已结束 TODO 最大条数；负数视为 0。
        :returns: 待归档的 TODO dict 列表（按原列表顺序，旧到新）。
        """
        keep = max(0, int(max_keep))
        todos = list(state.get("todos") or [])
        terminal = [
            todo for todo in todos if todo.get("status") in TERMINAL_TODO_STATUSES
        ]
        if len(terminal) <= keep:
            return []
        keep_ids = {str(todo.get("id")) for todo in terminal[len(terminal) - keep :]}
        archive_ids = {str(todo.get("id")) for todo in terminal} - keep_ids
        if not archive_ids:
            return []
        state["todos"] = [
            todo for todo in todos if str(todo.get("id")) not in archive_ids
        ]
        return [todo for todo in terminal if str(todo.get("id")) in archive_ids]

    def clear_completed(self, *, keep_recent: int = 2) -> dict[str, Any]:
        """显式归档「已结束」TODO（工具入口）。

        比 ``save()`` 的自动软上限更激进：只保留最新的 ``keep_recent`` 条已结束
        TODO 在主列表，其余全部归档。归档而非删除，完整保留历史。

        :param keep_recent: 主列表中保留的已结束 TODO 条数，默认 2。
        :returns: ``{"archived": 归档条数, "kept_terminal": 保留条数,
            "remaining": 主列表剩余总数, "state": 更新后状态}``。
        """
        keep = max(0, int(keep_recent))
        state = self.load()
        archived = self._archive_terminal(state, max_keep=keep)
        if archived:
            self._append_archive(archived)
        state = self.save(state)
        kept_terminal = sum(
            1 for todo in state["todos"] if todo.get("status") in TERMINAL_TODO_STATUSES
        )
        return {
            "archived": len(archived),
            "kept_terminal": kept_terminal,
            "remaining": len(state["todos"]),
            "state": state,
        }

    def list(
        self, *, status: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """列出 TODO。

        :param status: 可选状态过滤条件；None 表示不过滤。
        :param limit: 可选最大返回数量；None 表示不截断，负数也不截断。
        :returns: 包含 ``todos``、``count``、``active_todo_id`` 的 dict。
        """
        state = self.load()
        todos = state["todos"]
        if status:
            todos = [todo for todo in todos if todo["status"] == status]
        if limit is not None and limit >= 0:
            todos = todos[:limit]
        return {
            "todos": todos,
            "count": len(todos),
            "active_todo_id": state["active_todo_id"],
        }

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        """新增一条 TODO。

        :param payload: TODO 字段 dict；必须包含非空 title，其它字段走默认值或校验。
        :returns: ``{"todo": 新增条目, "state": 更新后状态}``。
        :raises ValueError: title 缺失或为空。
        :raises pydantic.ValidationError: payload 不满足核心 schema。
        """
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("todo_add requires non-empty title")
        state = self.load()
        used = {todo["id"] for todo in state["todos"]}
        todo = normalize_todo({**payload, "title": title}, existing_ids=used)
        state["todos"].append(todo)
        state = self.save(state)
        return {"todo": todo, "state": state}

    def update(self, todo_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """更新一条已有 TODO。

        :param todo_id: 要更新的 TODO id。
        :param patch: 局部字段补丁；id 不允许被 patch 改写。
        :returns: ``{"todo": 更新后条目, "state": 更新后状态}``。
        :raises ValueError: todo_id 为空或 patch 不是 dict。
        :raises KeyError: 找不到对应 TODO。
        :raises pydantic.ValidationError: 合并后的 TODO 不满足核心 schema。
        """
        todo_id = str(todo_id or "").strip()
        if not todo_id:
            raise ValueError("todo_update requires todo_id")
        if not isinstance(patch, dict):
            raise ValueError("todo_update requires patch object")
        state = self.load()
        for idx, todo in enumerate(state["todos"]):
            if todo["id"] != todo_id:
                continue
            merged = {**todo, **patch, "id": todo_id}
            state["todos"][idx] = normalize_todo(
                merged,
                existing_ids={t["id"] for t in state["todos"] if t["id"] != todo_id},
            )
            updated_todo = state["todos"][idx]
            if updated_todo["status"] == "active":
                state["active_todo_id"] = todo_id
            elif state["active_todo_id"] == todo_id:
                state["active_todo_id"] = None
            state = self.save(state)
            # 直接返回本次合并出的条目，而非在 save 后按 id 回查：自动归档可能
            # 已把该条移出主列表，回查会抛 StopIteration。归档只删除不改内容，
            # 因此合并后的条目即权威结果。
            return {"todo": updated_todo, "state": state}
        raise KeyError(f"todo not found: {todo_id}")

    def start(self, todo_id: str) -> dict[str, Any]:
        """把指定 TODO 设为唯一 active。

        :param todo_id: 要开始执行的 TODO id。
        :returns: ``{"todo": active 条目, "state": 更新后状态}``。
        :raises ValueError: todo_id 为空。
        :raises KeyError: 找不到对应 TODO。
        """
        todo_id = str(todo_id or "").strip()
        if not todo_id:
            raise ValueError("todo_start requires todo_id")
        state = self.load()
        found = False
        for todo in state["todos"]:
            if todo["id"] == todo_id:
                todo["status"] = "active"
                found = True
            elif todo["status"] == "active":
                todo["status"] = "pending"
        if not found:
            raise KeyError(f"todo not found: {todo_id}")
        state["active_todo_id"] = todo_id
        state = self.save(state)
        return {
            "todo": next(t for t in state["todos"] if t["id"] == todo_id),
            "state": state,
        }

    def complete(self, todo_id: str, outcome: str = "") -> dict[str, Any]:
        """完成指定 TODO。

        :param todo_id: 要完成的 TODO id。
        :param outcome: 可选完成结果说明，会写入 notes。
        :returns: ``{"todo": 完成后条目, "state": 更新后状态}``。
        """
        patch = {"status": "done"}
        if outcome:
            patch["notes"] = outcome
        result = self.update(todo_id, patch)
        state = result["state"]
        if state["active_todo_id"] == todo_id:
            state["active_todo_id"] = None
            state = self.save(state)
            result["state"] = state
            result["todo"] = next(t for t in state["todos"] if t["id"] == todo_id)
        return result

    def defer(
        self, todo_id: str, *, new_due: str | None = None, reason: str = ""
    ) -> dict[str, Any]:
        """推迟指定 TODO。

        :param todo_id: 要推迟的 TODO id。
        :param new_due: 可选新到期时间，必须是 ISO datetime 字符串或 None。
        :param reason: 可选推迟原因，会写入 blocking_reason。
        :returns: ``{"todo": 推迟后条目, "state": 更新后状态}``。
        """
        patch: dict[str, Any] = {
            "status": "deferred",
            "blocking_reason": reason or None,
        }
        if new_due is not None:
            patch["due"] = new_due
        return self.update(todo_id, patch)

    def build_prompt_context(self, now: datetime) -> dict[str, Any]:
        """构建注入 step prompt 的短 TODO 摘要。

        :param now: 当前模拟时间，用于判断 due_now 和 overdue。
        :returns: 一个短上下文 dict：``active`` 当前任务；``due_now`` 未来 30 分钟
            内到期的 pending/active，最多 3 条；``overdue_or_blocked`` 已过期或
            blocked 的任务，最多 2 条；``counts`` 各状态数量。

        .. note::

            这里故意不返回完整 TODO List，避免每轮 ReAct prompt 过长。
        """
        state = self.load()
        todos = state["todos"]
        active = next(
            (todo for todo in todos if todo["id"] == state["active_todo_id"]), None
        )
        soon = now + timedelta(minutes=30)

        def due_time(todo: dict[str, Any]) -> datetime | None:
            return _parse_time(todo.get("due"))

        due_now = [
            todo
            for todo in todos
            if todo["status"] in {"pending", "active"}
            and due_time(todo) is not None
            and due_time(todo) <= soon
        ]
        due_now.sort(
            key=lambda todo: (due_time(todo) or soon, -float(todo["priority"]))
        )

        overdue_or_blocked = [
            todo
            for todo in todos
            if todo["status"] == "blocked"
            or (
                todo["status"] in {"pending", "active", "deferred"}
                and due_time(todo) is not None
                and due_time(todo) < now
            )
        ]
        overdue_or_blocked.sort(
            key=lambda todo: (todo["status"] != "blocked", -(float(todo["priority"])))
        )

        return {
            "active": active,
            "due_now": due_now[:3],
            "overdue_or_blocked": overdue_or_blocked[:2],
            "counts": {
                status: sum(1 for todo in todos if todo["status"] == status)
                for status in sorted(TODO_STATUSES)
            },
        }

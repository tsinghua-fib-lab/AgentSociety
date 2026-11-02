"""基于工作区文件的核心记忆存储。

中文：为 PersonAgent 提供基于工作区文件的核心记忆存储。
English: Provides workspace-file storage for PersonAgent core memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

MEMORY_MD_PATH = "MEMORY.md"
MEMORY_DIR = "memory"
EPISODES_PATH = f"{MEMORY_DIR}/episodes.jsonl"
MEMORY_STATE_PATH = f"{MEMORY_DIR}/state.json"
MEMORY_STABLE_TYPES = {
    "identity",
    "preference",
    "relationship",
    "conflict",
    "resolution",
}

DEFAULT_MEMORY_MD = """# Memory

## Identity And Profile
- None recorded yet.

## Stable Preferences
- None recorded yet.

## Relationships
- None recorded yet.

## Durable Goals And Commitments
- None recorded yet.

## Important Past Events
- None recorded yet.

## Known Constraints
- None recorded yet.
"""


@dataclass(frozen=True)
class MemoryConsolidationConfig:
    """决定何时刷新 MEMORY.md 的配置。

    :param pending_threshold: 触发合并的待处理 episode 数量阈值。
    :param interval_steps: 触发合并的步数间隔。
    :param high_importance_threshold: 触发合并的重要性分数。
    :param max_memory_chars: MEMORY.md 提示上下文的期望最大尺寸。
    """

    pending_threshold: int = 10
    interval_steps: int = 8
    high_importance_threshold: float = 0.75
    max_memory_chars: int = 4000


MemoryEpisodeType = Literal[
    "commitment",
    "relationship",
    "preference",
    "goal",
    "conflict",
    "resolution",
    "identity",
    "observation",
    "routine",
]


class ExtractedMemoryEpisode(BaseModel):
    """已校验的 LLM 产出记忆点,尚未附加持久化元数据。

    :param type: 用于合并决策的记忆类别。
    :param importance: 0.0 到 1.0 之间的重要性分数。
    :param keywords: 便于 grep、供后续检索的关键词。
    :param text: 一条要记住的持久事实。
    :param source: 该记忆的来源标签。
    :param refs: 该记忆引用的可选记忆 ID。
    """

    type: MemoryEpisodeType = "observation"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    text: str = Field(min_length=1, max_length=1000)
    source: str = Field(default="step_result", max_length=80)
    refs: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("keywords", "refs", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        """将可选的类列表字段规范化为去重后的字符串列表。

        :param value: Pydantic 校验传入的原始字段值。
        :returns: 去除首尾空白且去重后的字符串列表。
        """
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result

    @field_validator("text", "source")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        """去除必填文本字段的首尾空白。

        :param value: 原始文本值。
        :returns: 去除首尾空白后的文本。
        """
        return value.strip()


class MemoryExtractionResult(BaseModel):
    """步骤记忆抽取的函数调用结果。

    :param memories: 从单个步骤抽取出的记忆点。
    """

    memories: list[ExtractedMemoryEpisode] = Field(default_factory=list, max_length=8)


class MemoryConsolidationResult(BaseModel):
    """Legacy public result model retained for SDK import compatibility."""

    memory_md: str = Field(min_length=1, max_length=20000)

    @field_validator("memory_md")
    @classmethod
    def _strip_memory_md(cls, value: str) -> str:
        return value.strip()


class AgentMemoryStore:
    """核心 agent 记忆的工作区文件存储。

    ``episodes.jsonl`` 是权威的 append-only 事件记忆源,
    ``MEMORY.md`` 是由 episodes 派生出的紧凑上下文。

    :param workspace_root: 单个 agent 工作区的根目录。
    :param agent_id: 持久化 episode 记录中使用的数字 agent id。
    """

    trigger_types: ClassVar[set[str]] = {
        "commitment",
        "relationship",
        "preference",
        "goal",
        "conflict",
        "resolution",
        "identity",
    }

    def __init__(self, workspace_root: Path, *, agent_id: int) -> None:
        """初始化基于文件的记忆存储。

        :param workspace_root: 单个 agent 工作区的根目录。
        :param agent_id: 记忆记录中使用的数字 agent id。
        :returns: 无返回值。
        """
        self.root = workspace_root
        self.agent_id = agent_id
        # Lazily-loaded in-memory mirror of episodes.jsonl. Avoids re-reading +
        # re-parsing the whole file on every iter_episodes()/search()/range()
        # call (was O(n) per call and blocked the event loop). Single-writer
        # (append_episodes) keeps it consistent; set to None to force a reload.
        self._episodes_cache: list[dict[str, Any]] | None = None

    @property
    def memory_md_path(self) -> Path:
        """返回 MEMORY.md 的路径。

        :returns: MEMORY.md 的绝对路径。
        """
        return self.root / MEMORY_MD_PATH

    @property
    def episodes_path(self) -> Path:
        """返回 episodes JSONL 文件的路径。

        :returns: memory/episodes.jsonl 的绝对路径。
        """
        return self.root / EPISODES_PATH

    @property
    def state_path(self) -> Path:
        """返回记忆状态文件的路径。

        :returns: memory/state.json 的绝对路径。
        """
        return self.root / MEMORY_STATE_PATH

    def ensure(self) -> None:
        """在记忆文件不存在时创建它们。

        :returns: 无返回值。
        """
        (self.root / MEMORY_DIR).mkdir(parents=True, exist_ok=True)
        if not self.episodes_path.exists():
            self.episodes_path.write_text("", encoding="utf-8")
        if not self.memory_md_path.exists():
            self.memory_md_path.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")
        if not self.state_path.exists():
            self.write_state(self.default_state())

    def default_state(self) -> dict[str, Any]:
        """构造默认的记忆状态。

        :returns: 新的默认记忆状态字典。
        """
        return {
            "schema_version": 1,
            "last_consolidated_tick": None,
            "last_consolidated_episode_id": None,
            "last_consolidated_step": 0,
            "pending_episode_count": 0,
            "episode_counter": 0,
            # Consolidation fuse (Phase 1.8c): empty LLM merges don't advance
            # the cursor, so they would otherwise re-fire every step. The
            # streak counts consecutive empty results; once it hits 2, attempts
            # pause until ``consolidation_cooldown_until_step``. Both survive
            # agent rebuilds because agents are rehydrated from this state
            # every tick.
            "consolidation_empty_streak": 0,
            "consolidation_cooldown_until_step": 0,
        }

    def read_state(self) -> dict[str, Any]:
        """从磁盘读取记忆状态。

        :returns: 与默认键合并后的状态字典。
        """
        self.ensure()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        state = self.default_state()
        if isinstance(data, dict):
            state.update(data)
        return state

    def write_state(self, state: dict[str, Any]) -> None:
        """将记忆状态写入磁盘。

        :param state: 要持久化的状态字典。
        :returns: 无返回值。
        """
        (self.root / MEMORY_DIR).mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def read_memory_md(self, *, max_chars: int | None = None) -> str:
        """读取紧凑的长期记忆。

        :param max_chars: 可选的字符预算,超长内容会被截断。
        :returns: MEMORY.md 文本,可能被截断。
        """
        self.ensure()
        text = self.memory_md_path.read_text(encoding="utf-8")
        if max_chars is not None and max_chars > 0 and len(text) > max_chars:
            return text[:max_chars] + "\n...<truncated>"
        return text

    def write_memory_md(
        self, content: str, *, step_count: int, tick: int | None
    ) -> None:
        """写入紧凑的长期记忆并更新合并状态。

        :param content: 完整的 MEMORY.md 内容。
        :param step_count: 当前 agent 步数。
        :param tick: 当前仿真 tick(可用时)。
        :returns: 无返回值。
        """
        self.ensure()
        text = self.normalize_memory_md(
            content,
            max_chars=MemoryConsolidationConfig().max_memory_chars,
        )
        self.memory_md_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        state = self.read_state()
        last = self.recent(limit=1)
        state.update(
            {
                "last_consolidated_tick": tick,
                "last_consolidated_episode_id": last[0]["id"] if last else None,
                "last_consolidated_step": step_count,
                "pending_episode_count": 0,
            }
        )
        self.write_state(state)

    def normalize_memory_md(
        self,
        content: str,
        *,
        max_chars: int = 4000,
    ) -> str:
        """对 LLM 产出的 MEMORY.md 内容应用最小的结构保障。

        合并提示词已要求 LLM 直接返回格式良好的 Markdown;本函数只确保
        顶层标题存在并限制长度,刻意不重排、不改写文本。

        :param content: LLM 产出的原始 MEMORY.md 内容。
        :param max_chars: 输出的最大字符预算。
        :returns: 带顶层标题且长度受限的 MEMORY.md 文本。
        """
        text = str(content or "").strip()
        if not text:
            text = DEFAULT_MEMORY_MD.strip()
        if not text.lstrip().startswith("#"):
            text = "# Memory\n\n" + text
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return text.rstrip() + "\n"

    def append_episodes(
        self,
        episodes: list[dict[str, Any]],
        *,
        tick: int,
        t: datetime,
        step_count: int,
    ) -> list[dict[str, Any]]:
        """追加规范化后的记忆 episodes 并返回写入的记录。

        :param episodes: 记忆抽取器给出的原始 episode 字典。
        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :param step_count: 当前 agent 步数。
        :returns: 写入 memory/episodes.jsonl 的 episode 记录。
        """
        self.ensure()
        state = self.read_state()
        counter = int(state.get("episode_counter") or 0)
        written: list[dict[str, Any]] = []
        for raw in episodes:
            text = " ".join(str(raw.get("text") or "").strip().split())
            if not text:
                continue
            counter += 1
            keywords_raw = raw.get("keywords")
            keywords = (
                [str(item).strip() for item in keywords_raw if str(item).strip()]
                if isinstance(keywords_raw, list)
                else []
            )
            refs_raw = raw.get("refs")
            refs = (
                [str(item).strip() for item in refs_raw if str(item).strip()]
                if isinstance(refs_raw, list)
                else []
            )
            try:
                importance = float(raw.get("importance", 0.5))
            except Exception:
                importance = 0.5
            importance = max(0.0, min(1.0, importance))
            record = {
                "id": f"m_{tick:08d}_{counter:06d}",
                "agent_id": self.agent_id,
                "tick": tick,
                "tick_duration_sec": tick,
                "step_index": step_count,
                "time": t.isoformat(),
                "step_count": step_count,
                "type": str(raw.get("type") or "observation").strip() or "observation",
                "importance": importance,
                "keywords": keywords,
                "text": text,
                "source": str(raw.get("source") or "step_result").strip()
                or "step_result",
                "refs": refs,
            }
            written.append(record)
        if not written:
            return []

        with self.episodes_path.open("a", encoding="utf-8") as f:
            for record in written:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        # Keep the in-memory cache in sync. If the cache was never loaded, leave
        # it None — a later iter_episodes() will lazy-load from disk (which now
        # includes these records). Single-writer per store → no race.
        if self._episodes_cache is not None:
            self._episodes_cache.extend(written)
        state["episode_counter"] = counter
        state["pending_episode_count"] = int(
            state.get("pending_episode_count") or 0
        ) + len(written)
        self.write_state(state)
        return written

    def iter_episodes(self) -> list[dict[str, Any]]:
        """读取全部有效的记忆 episodes。

        使用内存缓存(首次访问时加载一次,由 append_episodes 保持同步),
        重复调用不再重新读取/解析整个 episodes.jsonl。返回浅拷贝,调用方
        无法修改缓存。

        :returns: 按文件顺序排列的已解析 episode 字典。
        """
        return list(self._load_episodes_cache())

    def _load_episodes_cache(self) -> list[dict[str, Any]]:
        """惰性地从磁盘加载并缓存全部 episodes。

        :returns: 内存中的 episode 列表(即缓存本身)。
        """
        if self._episodes_cache is None:
            self.ensure()
            records: list[dict[str, Any]] = []
            for line in self.episodes_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    records.append(item)
            self._episodes_cache = records
        return self._episodes_cache

    def recent(self, *, limit: int = 8) -> list[dict[str, Any]]:
        """读取最近的记忆 episodes。

        :param limit: 返回的最大 episode 数量。
        :returns: 按时间先后排列的最新 episode 字典。
        """
        limit = max(1, int(limit or 8))
        return self.iter_episodes()[-limit:]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """按子串搜索记忆 episodes。

        :param query: 在序列化后的 episode 中搜索的大小写不敏感子串。
        :param limit: 返回的最大匹配数量。
        :returns: 匹配的 episode 字典,最新在前。
        """
        q = str(query or "").strip().lower()
        if not q:
            return []
        limit = max(1, int(limit or 20))
        matches: list[dict[str, Any]] = []
        for item in reversed(self.iter_episodes()):
            haystack = json.dumps(item, ensure_ascii=False).lower()
            if q in haystack:
                matches.append(item)
            if len(matches) >= limit:
                break
        return matches

    def read_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """按 id 精确读取记忆 episodes。

        :param ids: 要读取的记忆 episode ID 列表。
        :returns: ID 与输入列表匹配的 episode 字典。
        """
        wanted = {str(item).strip() for item in ids if str(item).strip()}
        if not wanted:
            return []
        return [item for item in self.iter_episodes() if str(item.get("id")) in wanted]

    def range(
        self,
        *,
        start_step: int | None = None,
        end_step: int | None = None,
        start_tick: int | None = None,
        end_tick: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按 step、tick 时长或时间范围读取记忆 episodes。

        :param start_step: 含端点的 step-index 下界。
        :param end_step: 含端点的 step-index 上界。
        :param start_tick: 含端点的 tick 下界。
        :param end_tick: 含端点的 tick 上界。
        :param start_time: 含端点的 ISO datetime 下界。
        :param end_time: 含端点的 ISO datetime 上界。
        :param limit: 返回的最大 episode 数量。
        :returns: 按时间先后排列的匹配 episode 字典。
        """
        start_dt = self._parse_dt(start_time)
        end_dt = self._parse_dt(end_time)
        result: list[dict[str, Any]] = []
        for item in self.iter_episodes():
            step_index = self._episode_step_index(item)
            if start_step is not None and (
                step_index is None or step_index < start_step
            ):
                continue
            if end_step is not None and (step_index is None or step_index > end_step):
                continue
            tick = self._episode_tick_duration(item)
            if start_tick is not None and (tick is None or tick < start_tick):
                continue
            if end_tick is not None and (tick is None or tick > end_tick):
                continue
            item_dt = self._parse_dt(str(item.get("time") or ""))
            if start_dt is not None and (item_dt is None or item_dt < start_dt):
                continue
            if end_dt is not None and (item_dt is None or item_dt > end_dt):
                continue
            result.append(item)
            if len(result) >= max(1, int(limit or 50)):
                break
        return result

    @staticmethod
    def _episode_step_index(item: dict[str, Any]) -> int | None:
        """从记忆 episode 中返回事件 step index。

        :param item: 记忆 episode 字典。
        :returns: 存在且可解析时返回 step index,否则返回 None。
        """
        for key in ("step_index", "step_count"):
            raw = item.get(key)
            if isinstance(raw, int) or str(raw).isdigit():
                return int(raw)
        return None

    @staticmethod
    def _episode_tick_duration(item: dict[str, Any]) -> int | None:
        """从记忆 episode 中返回每步的 tick 时长。

        :param item: 记忆 episode 字典。
        :returns: 存在且可解析时返回以秒计的 tick 时长,否则返回 None。
        """
        for key in ("tick_duration_sec", "tick"):
            raw = item.get(key)
            if isinstance(raw, int) or str(raw).isdigit():
                return int(raw)
        return None

    def should_consolidate(
        self,
        new_episodes: list[dict[str, Any]],
        *,
        step_count: int,
        config: MemoryConsolidationConfig,
    ) -> tuple[bool, str]:
        """判断是否应刷新 MEMORY.md。

        :param new_episodes: 新追加的 episode 记录。
        :param step_count: 当前 agent 步数。
        :param config: 合并触发配置。
        :returns: ``(should_consolidate, reason)`` 二元组。
        """
        self.ensure()
        if not self.memory_md_path.exists():
            return True, "MEMORY.md missing"
        memory_text = self.memory_md_path.read_text(encoding="utf-8")
        if len(memory_text) > config.max_memory_chars:
            return True, "MEMORY.md exceeds context budget"
        for item in new_episodes:
            item_type = str(item.get("type") or "").strip().lower()
            is_candidate = self.is_long_term_memory_candidate(item)
            if (
                is_candidate
                and self._episode_importance(item) >= config.high_importance_threshold
            ):
                return True, "high-importance episode"
            if (
                is_candidate
                and item_type in self.trigger_types
                and item_type != "identity"
            ):
                return True, "trigger episode type"
        state = self.read_state()
        if int(state.get("pending_episode_count") or 0) >= config.pending_threshold:
            if any(
                self.is_long_term_memory_candidate(item)
                for item in self.unconsolidated()
            ):
                return True, "pending episode threshold"
        last_step = int(state.get("last_consolidated_step") or 0)
        if step_count - last_step >= config.interval_steps and any(
            self.is_long_term_memory_candidate(item) for item in self.unconsolidated()
        ):
            return True, "consolidation interval"
        return False, ""

    @staticmethod
    def _episode_importance(episode: dict[str, Any]) -> float:
        """从 episode 中返回限界后的重要性分数。

        :param episode: 已持久化或候选的记忆 episode。
        :returns: 0.0 到 1.0 之间的重要性分数。
        """
        try:
            importance = float(episode.get("importance") or 0.0)
        except Exception:
            importance = 0.0
        return max(0.0, min(1.0, importance))

    @classmethod
    def is_long_term_memory_candidate(cls, episode: dict[str, Any]) -> bool:
        """返回某个 episode 是否应纳入 MEMORY.md 合并。

        :param episode: 已持久化或候选的记忆 episode。
        :returns: 当 LLM 给出的结构将 episode 标记为足够持久、应纳入合并
            提示时返回 True。
        """
        episode_type = str(episode.get("type") or "").strip().lower()
        importance = cls._episode_importance(episode)
        if episode_type in MEMORY_STABLE_TYPES:
            return True
        if episode_type in {"commitment", "goal"}:
            return importance >= 0.6
        if episode_type == "observation":
            return importance >= 0.85
        return False

    def unconsolidated(self) -> list[dict[str, Any]]:
        """读取上次合并游标之后写入的 episodes。

        :returns: 尚未合并进 MEMORY.md 的 episode 字典。
        """
        state = self.read_state()
        last_id = state.get("last_consolidated_episode_id")
        records = self.iter_episodes()
        if not last_id:
            return records
        for idx, item in enumerate(records):
            if item.get("id") == last_id:
                return records[idx + 1 :]
        return records

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """尽可能解析 ISO datetime 字符串。

        :param value: 可选的 datetime 字符串。
        :returns: 解析成功返回 datetime,失败返回 None。
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

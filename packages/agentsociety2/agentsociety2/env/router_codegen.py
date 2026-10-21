"""
Code Generation Router Implementation
通过代码生成的方式调用环境模块中的@tool标记的接口

架构说明:
- AskContext: 一次ask调用所需的所有状态
- 观察者模式: 流程结束后统一将 context 交给所有 observer 记录
- 管道-过滤器: 整体流程通过 PipelineStage 串联
- 责任链: Code 获取通过 CodeProvider 链实现 (PredefinedCode -> Cache -> LLM)
- CodeStage: 单阶段完成代码获取 + 验证 + 执行
"""

import ast
import asyncio
import inspect
import json
import math
import os
import pickle
import random
import re
import sys
import time
import types
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Protocol

if TYPE_CHECKING:
    from agentsociety2.storage import ReplayWriter

import faiss
import numpy as np
from litellm import AllMessageValues, aembedding

from agentsociety2.config import Config
from agentsociety2.env.base import EnvBase
from agentsociety2.env.router_base import RouterBase
from agentsociety2.logger import get_logger

__all__ = ["AskContext", "CodeGenRouter"]


@dataclass
class CacheStats:
    """缓存统计信息"""

    request_count: int = 0  # 总请求次数
    predefined_hit_count: int = 0  # 预定义指令命中次数（observe/statistics）
    cache_hit_count: int = 0  # 缓存命中次数
    cache_miss_count: int = 0  # 缓存未命中次数
    total_input_tokens: int = 0  # 总输入token数
    total_output_tokens: int = 0  # 总输出token数
    code_execution_success_count: int = 0  # 代码执行成功次数
    code_execution_failure_count: int = 0  # 代码执行失败次数
    total_code_retry_count: int = 0  # 总代码重试次数

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率"""
        total = self.cache_hit_count + self.cache_miss_count
        return self.cache_hit_count / total if total > 0 else 0.0

    @property
    def code_execution_success_rate(self) -> float:
        """代码执行成功率"""
        total = self.code_execution_success_count + self.code_execution_failure_count
        return self.code_execution_success_count / total if total > 0 else 0.0

    @property
    def avg_input_tokens(self) -> float:
        """平均输入token数"""
        return (
            self.total_input_tokens / self.request_count
            if self.request_count > 0
            else 0.0
        )

    @property
    def avg_output_tokens(self) -> float:
        """平均输出token数"""
        return (
            self.total_output_tokens / self.request_count
            if self.request_count > 0
            else 0.0
        )

    @property
    def avg_retry_count(self) -> float:
        """平均代码重试次数"""
        return (
            self.total_code_retry_count / self.request_count
            if self.request_count > 0
            else 0.0
        )


@dataclass
class CacheEntry:
    """缓存条目"""

    instruction_template: str  # 模板指令
    # 创建该条目那次调用传入的变量键快照：既非模板需要哪些键，也非代码实际
    # 读取哪些键。缓存复用判定首选 _code_variable_reads（代码必读键），
    # 仅当代码无法静态分析时才退回以该快照做保守子集检查。
    variable_keys: tuple[str, ...]
    variable_types: dict[str, str]  # 变量类型字典 {key: type_name}
    code: str  # 生成的代码
    embedding: np.ndarray | None = None  # 指令的embedding（用于相似度计算）
    env_class_type: str = ""  # 接入的env module classes指纹，仅一致时才能使用
    entry_id: int | None = None  # 数据库中的条目ID（持久化时使用）
    success_count: int = 0  # 成功执行次数
    failure_count: int = 0  # 失败执行次数
    last_used: datetime = field(default_factory=datetime.now)  # 最后使用时间
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间

    @property
    def total_usage(self) -> int:
        """总使用次数"""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


# ═══════════════════════════════════════════════════════════
# Template cache reuse criterion: what the code actually reads
# ═══════════════════════════════════════════════════════════

# _code_variable_reads 结果按代码文本缓存：dedup 路径会整段覆盖 entry.code，
# 按内容做键天然自失效；纯 CPU、仅事件循环内同步调用，无需加锁。
_code_reads_memo: dict[str, frozenset[str] | None] = {}
_CODE_READS_MEMO_MAX = 8192


def _is_variables_mapping_expr(node: ast.AST | None, aliases: set[str]) -> bool:
    """node 是否（直接或经别名）指向 ``ctx['variables']`` 映射本身。"""
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Subscript):
        return (
            isinstance(node.value, ast.Name)
            and node.value.id == "ctx"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "variables"
        )
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ctx"
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "variables"
        )
    return False


def _compute_code_variable_reads(code: str) -> frozenset[str] | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    # 第一遍：收集指向 variables 映射的别名（含链式别名 w = v），迭代到不
    # 动点；出现无法跟踪的绑定（元组/属性目标、别名改绑）即整体不可分析。
    assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    aliases: set[str] = set()
    while True:
        grew = False
        for node in assigns:
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                alias_val = _is_variables_mapping_expr(value, aliases) or (
                    isinstance(value, ast.Name) and value.id in aliases
                )
                if isinstance(target, ast.Name):
                    if alias_val and target.id not in aliases:
                        aliases.add(target.id)
                        grew = True
                    elif target.id in aliases and not alias_val:
                        return None  # 别名被改绑到其他对象，后续读取无法判定
                elif alias_val:
                    return None  # 映射逃逸到属性/元组等目标，无法跟踪
        if not grew:
            break

    # 第二遍：对映射的每种使用都必须能静态判定——常量下标计入必读键；
    # .get 带默认值语义、缺键不抛错，不计入；其余任何形态（动态下标、
    # .items()、传参、迭代等）一律整体判为不可分析。
    required: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_variables_mapping_expr(
            node.value, aliases
        ):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                required.add(sl.value)
            else:
                return None  # 动态键
            continue
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "get"
            and _is_variables_mapping_expr(node.value, aliases)
        ):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_variables_mapping_expr(
            node.value, aliases
        ):
            continue
        for child in ast.iter_child_nodes(node):
            if _is_variables_mapping_expr(child, aliases):
                return None
    return frozenset(required)


def _code_variable_reads(code: str) -> frozenset[str] | None:
    """静态提取代码必读的 ``ctx['variables']`` 键。

    返回 ``None`` 表示代码以无法静态分析的形态使用了 variables（动态下标、
    迭代、别名逃逸等），调用方需退回保守判据。
    """
    if code in _code_reads_memo:
        return _code_reads_memo[code]
    result = _compute_code_variable_reads(code)
    if len(_code_reads_memo) >= _CODE_READS_MEMO_MAX:
        _code_reads_memo.clear()
    _code_reads_memo[code] = result
    return result


def _entry_usable_with(entry: CacheEntry, current_keys: set[str]) -> bool:
    """缓存条目的代码能否在当前这组 variables 下复用。

    首选“代码必读变量 ⊆ 当前变量”（多带的无关键不构成障碍，缺必读键才
    否决）；代码不可静态分析时退回“variable_keys ⊆ 当前变量”的保守旧判据。
    """
    reads = _code_variable_reads(entry.code)
    if reads is None:
        return set(entry.variable_keys) <= current_keys
    return reads <= current_keys


# ═══════════════════════════════════════════════════════════
# AST guard: ensure LLM-generated code awaits async tool calls
# ═══════════════════════════════════════════════════════════


def _collect_async_tool_names(router: "CodeGenRouter") -> set[str]:
    """Collect the names of all async ``@tool`` methods across env modules.

    Used by :func:`_ensure_await_async_calls` to know which calls in
    LLM-generated code need ``await``.
    """
    names: set[str] = set()
    for module in router._modules.values():
        for entry in getattr(module, "_llm_tools", []):
            name = entry.get("function", {}).get("name", "")
            if not name:
                continue
            fn = getattr(module, name, None)
            if fn is not None and inspect.iscoroutinefunction(fn):
                names.add(name)
    return names


class _EnsureAwaitTransformer(ast.NodeTransformer):
    """Wrap calls to known async functions in ``Await`` nodes.

    If the LLM forgets ``await`` before an async tool call (e.g.
    ``person = get_person(agent_id)``), this transformer rewrites it
    to ``person = await get_person(agent_id)`` at the AST level —
    no regex, no false positives.

    Already-awaited calls are left untouched (``visit_Await`` skips
    the direct child Call but still visits its arguments for nested
    un-awaited calls).
    """

    def __init__(self, async_names: set[str]) -> None:
        self._async_names = async_names

    def _targets_async(self, node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in self._async_names:
            return True
        return bool(isinstance(func, ast.Name) and func.id in self._async_names)

    def visit_Await(self, node: ast.Await) -> Any:
        """Don't visit the awaited Call itself (prevent double-wrap).

        But DO visit its args/kwargs (nested calls might need await).
        """
        if isinstance(node.value, ast.Call):
            call = node.value
            call.args = [self.visit(arg) for arg in call.args]
            for kw in call.keywords:
                kw.value = self.visit(kw.value)
        return node

    def visit_Call(self, node: ast.Call) -> Any:
        self.generic_visit(node)  # nested calls in args first
        if self._targets_async(node):
            return ast.Await(value=node)
        return node


def _ensure_await_async_calls(code: str, async_names: set[str]) -> str:
    """AST-transform generated code so async tool calls use ``await``.

    Multi-layer guard (Layer 1):
    - Parse the code → AST.
    - Wrap every un-awaited Call to an async tool in an Await node.
    - Unparse back to source.

    Layers 2-3 (already present):
    - ``clean_coroutines_from_results`` catches coroutines in results.
    - Error-feedback retry on execution failure.

    Falls back to the original code on parse error (SyntaxError).
    """
    if not async_names:
        return code
    try:
        tree = ast.parse(code)
        tree = _EnsureAwaitTransformer(async_names).visit(tree)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    except SyntaxError:
        return code


OBSERVE_INSTRUCTION = (
    "Generate code that calls every available observe tool for this agent, "
    "extracting the agent id (agent_id / id / person_id) from ctx. After "
    "collecting the results, print a concise natural-language summary of the "
    "agent's current situation (status, location, ongoing activity/event, and "
    "anything notable) as complete sentences — this summary is shown to the "
    "agent verbatim. Also store the raw results in results['observations']."
)
STATISTICS_INSTRUCTION = "Collect environment statistics by calling all available statistics tools. Store all statistics results in results['statistics']."


@dataclass
class AskContext:
    """
    一次ask调用所需的完整状态，在管道各阶段之间传递。
    """

    # === 输入 ===
    ctx: dict
    instruction: str
    readonly: bool
    template_mode: bool

    # === 预处理后 ===
    variables: dict = field(default_factory=dict)
    instruction_stripped: str = ""
    is_observe_or_statistics: bool = False
    resolved_instruction: str = ""  # <observe>/<statistics> 解析后的实际指令

    # === Code 获取 (责任链) ===
    code: str | None = None
    cache_entry: Optional["CacheEntry"] = None
    cache_miss_reason: str | None = None
    code_source: str | None = None  # "predefined" | "cache" | "llm" | "builtin"

    # === LLM 重试状态 ===
    retry_count: int = 0
    previous_code: str | None = None
    previous_errors: list[str] = field(default_factory=list)
    dialog_history: list[AllMessageValues] = field(default_factory=list)

    # === 执行结果 ===
    execution_result: dict[str, Any] | None = None
    execution_attempted: bool = False  # 是否尝试过执行代码（供 observer 统计）
    success_data: dict[str, Any] | None = (
        None  # 成功时的 {ctx, instruction, results, process_text, status, error, code}
    )

    # === 输出 ===
    final_answer: str = ""
    results: dict = field(default_factory=dict)
    early_return: tuple[dict, str] | None = None  # 非 None 表示提前返回，不再继续管道
    token_usage_responses: list[dict[str, int]] = field(
        default_factory=list
    )  # 每次 LLM 调用的 token 使用，供 observer 统计

    def __post_init__(self):
        self.instruction_stripped = self.instruction.strip()
        self.is_observe_or_statistics = self.instruction_stripped in (
            "<observe>",
            "<statistics>",
        )
        self.variables = self.ctx.get("variables", {})
        self.resolved_instruction = self.instruction
        if self.instruction_stripped == "<observe>":
            self.resolved_instruction = OBSERVE_INSTRUCTION
        elif self.instruction_stripped == "<statistics>":
            self.resolved_instruction = STATISTICS_INSTRUCTION


def _get_debug_info(description: str = "") -> str:
    """获取当前文件、行号和阶段描述的调试信息"""
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller_frame = frame.f_back
        filename = os.path.basename(caller_frame.f_code.co_filename)
        lineno = caller_frame.f_lineno
        return f"[{filename}:{lineno}] {description}"
    return description


async def clean_coroutines_from_results(results: dict) -> dict:
    """
    递归检查 results 中的未 await 的 coroutine 并 await 获取其值。
    供 CodeStage 使用。
    """
    visited: set[int] = set()

    async def clean_value(value: Any) -> Any:
        if inspect.iscoroutine(value):
            try:
                return await value
            except Exception as e:
                get_logger().warning(f"Failed to await coroutine: {e!s}")
                return f"<unawaited_coroutine: {type(value).__name__}>"
        elif isinstance(value, dict):
            obj_id = id(value)
            if obj_id in visited:
                return "<circular_reference>"
            visited.add(obj_id)
            try:
                return {k: await clean_value(v) for k, v in value.items()}
            finally:
                visited.remove(obj_id)
        elif isinstance(value, (list, tuple)):
            obj_id = id(value)
            if obj_id in visited:
                return "<circular_reference>"
            visited.add(obj_id)
            try:
                cleaned = [await clean_value(item) for item in value]
                return cleaned if isinstance(value, list) else tuple(cleaned)
            finally:
                visited.remove(obj_id)
        return value

    return await clean_value(results)


def _get_env_class_type_key(env_modules: list) -> str:
    """
    根据 env module classes 生成可读的标识字符串。
    相同 env 配置（模块类型和名称）产生相同 key，用于缓存隔离。
    返回 human-readable 的 JSON，便于直接查看缓存内容。
    """
    keys = []
    for m in env_modules:
        cls = m.__class__
        full_name = f"{cls.__module__}.{cls.__qualname__}"
        keys.append((m.name, full_name))
    return json.dumps(sorted(keys), sort_keys=True, ensure_ascii=False)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            stripped = "\n".join(lines[1:-1]).strip()
    return stripped


def _compact_results_text(results: dict[str, Any]) -> str:
    try:
        return json.dumps(
            results, ensure_ascii=False, separators=(",", ":"), default=str
        )
    except TypeError:
        return str(results)


def _build_deterministic_final_answer(
    router: "CodeGenRouter", success_data: dict[str, Any]
) -> str:
    time_tag = f"[{router.t.strftime('%A')}, {router.t.strftime('%Y-%m-%d %H:%M:%S')}]"
    status = success_data.get("status", "unknown")
    results = success_data.get("results", {})
    reason = results.get("reason") or success_data.get("error")
    process_text = _strip_code_fence(success_data.get("process_text", ""))

    if status in {"fail", "error"} and reason:
        body = str(reason).strip()
    elif process_text and process_text != "无输出":
        body = process_text
    elif reason:
        body = str(reason).strip()
    else:
        body = _compact_results_text(results)

    return f"{time_tag} {body}" if body else time_tag


class TemplateCacheDB:
    """
    持久化模板缓存，支持跨运行共用。
    使用 pickle 文件存储，FAISS 进行 embedding 相似度搜索。
    缓存按 env_class_type 隔离，仅 env 类型一致时才能命中。
    """

    def __init__(
        self,
        cache_path: str,
        embedding_dims: int,
        max_size_per_env: int = 1000,
    ):
        self._cache_path = cache_path
        self._embedding_dims = embedding_dims
        self._max_size_per_env = max_size_per_env
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    def _load_data(self) -> dict:
        """从 pickle 文件加载数据。"""
        if not os.path.exists(self._cache_path):
            return {"next_id": 1, "by_env": {}}
        try:
            with open(self._cache_path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            get_logger().warning(f"Failed to load cache from {self._cache_path}: {e}")
            return {"next_id": 1, "by_env": {}}

    def _save_data(self, data: dict) -> None:
        """保存数据到 pickle 文件。"""
        with open(self._cache_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load_entries(
        self, env_class_type: str
    ) -> tuple[list[CacheEntry], Optional["faiss.Index"], list[int]]:
        """
        加载指定 env_class_type 的缓存条目并构建 FAISS 索引。
        :returns: (entries, faiss_index, faiss_entry_indices)
        """
        data = self._load_data()
        raw = data.get("by_env", {}).get(env_class_type, [])
        raw = sorted(raw, key=lambda e: e.last_used, reverse=True)[
            : self._max_size_per_env
        ]

        entries: list[CacheEntry] = []
        embeddings: list[np.ndarray] = []
        entry_indices: list[int] = []

        for i, e in enumerate(raw):
            e.env_class_type = env_class_type
            entries.append(e)
            if e.embedding is not None:
                embeddings.append(e.embedding)
                entry_indices.append(i)

        if not embeddings:
            return entries, None, []

        emb_array = np.asarray(embeddings, dtype=np.float32).copy()
        faiss.normalize_L2(emb_array)
        index = faiss.IndexFlatIP(len(embeddings[0]))
        index.add(emb_array)
        return entries, index, entry_indices

    def add_entry(
        self,
        env_class_type: str,
        entry: CacheEntry,
    ) -> int:
        """新增缓存条目并持久化。Returns 新条目的 id。"""
        data = self._load_data()
        next_id = data.get("next_id", 1)
        by_env = data.setdefault("by_env", {})
        lst = by_env.setdefault(env_class_type, [])

        entry.entry_id = next_id
        entry.env_class_type = env_class_type
        lst.append(entry)
        lst.sort(key=lambda e: e.last_used, reverse=True)
        by_env[env_class_type] = lst[: self._max_size_per_env]

        data["next_id"] = next_id + 1
        self._save_data(data)
        return next_id

    def update_entry(
        self,
        env_class_type: str,
        entry_id: int,
        success: bool,
        code: str,
    ) -> None:
        """更新已有条目的统计和代码。"""
        data = self._load_data()
        lst = data.get("by_env", {}).get(env_class_type, [])
        for e in lst:
            if e.entry_id == entry_id:
                e.last_used = datetime.now()
                e.code = code
                if success:
                    e.success_count += 1
                else:
                    e.failure_count += 1
                break
        self._save_data(data)

    def clear_env_cache(self, env_class_type: str) -> None:
        """清空指定 env_class_type 的所有缓存条目。"""
        data = self._load_data()
        data.setdefault("by_env", {}).pop(env_class_type, None)
        self._save_data(data)

    def find_by_instruction(
        self,
        env_class_type: str,
        instruction_template: str,
    ) -> CacheEntry | None:
        """按 instruction_template 查找已有条目（用于更新而非新增）。"""
        data = self._load_data()
        lst = data.get("by_env", {}).get(env_class_type, [])
        for e in lst:
            if e.instruction_template == instruction_template:
                return e
        return None


# ==================== 观察者模式 ====================
# 所有 observer 仅在流程结束时被调用一次，根据完整 context 记录必要内容


class AskObserver(Protocol):
    """Ask流程观察者协议：流程结束后接收最终 context"""

    async def on_final(self, context: AskContext) -> None:
        raise NotImplementedError


# ==================== 责任链：Code 获取 ====================


class CodeProvider(Protocol):
    """Code 获取责任链节点协议，Predefined 最优先"""

    @property
    def name(self) -> str:
        """提供者名称，用于 context.code_source"""
        raise NotImplementedError

    async def get_code(
        self, context: AskContext, router: "CodeGenRouter"
    ) -> str | None:
        """返回代码则链终止，返回 None 则传递至下一节点"""
        raise NotImplementedError


# ==================== 管道-过滤器 ====================


class PipelineStage(Protocol):
    """管道阶段协议，接收 AskContext，返回可能被修改的 AskContext"""

    async def process(self, context: AskContext, router: "CodeGenRouter") -> AskContext:
        raise NotImplementedError


# --- 观察者具体实现：统一在 on_final 中根据 context 记录 ---


class CacheStatsObserver:
    """根据最终 context 更新 CacheStats 统计"""

    def __init__(self, router: "CodeGenRouter"):
        self._router = router

    async def on_final(self, context: AskContext) -> None:
        async with self._router._cache_stats_lock:
            self._router._cache_stats.request_count += 1
            if context.code_source in ("predefined", "builtin"):
                self._router._cache_stats.predefined_hit_count += 1
            elif context.cache_entry:
                self._router._cache_stats.cache_hit_count += 1
            elif context.template_mode and not context.is_observe_or_statistics:
                self._router._cache_stats.cache_miss_count += 1
            if context.execution_attempted:
                if context.success_data:
                    self._router._cache_stats.code_execution_success_count += 1
                else:
                    self._router._cache_stats.code_execution_failure_count += 1
                self._router._cache_stats.total_code_retry_count += context.retry_count
            for tu in context.token_usage_responses:
                self._router._cache_stats.total_input_tokens += tu.get(
                    "input_tokens", 0
                )
                self._router._cache_stats.total_output_tokens += tu.get(
                    "output_tokens", 0
                )


class CacheAddObserver:
    """执行成功后根据条件写入缓存"""

    def __init__(self, router: "CodeGenRouter"):
        self._router = router

    @staticmethod
    async def _add_to_cache(
        router: "CodeGenRouter",
        instruction: str,
        variables: dict,
        code: str,
        success: bool = True,
    ) -> None:
        if not router._template_cache_enabled:
            return
        # Embedding（可能是一次 embedding HTTP 调用）必须在 _template_cache_lock
        # 之外计算：该锁同时守护 _lookup（每次 ask），锁内 await 会把并行 ask 串行
        # 化到 embedding 端点的延迟上。_compute_embedding 自带缓存与独立锁，
        # 并发调用安全；锁内剩余工作（DB 查询/faiss 更新）是纯 CPU，仍串行。
        embedding = await CacheCodeProvider._compute_embedding(router, instruction)
        async with router._template_cache_lock:
            # variable_keys 是"本次调用传了哪些键"的快照，语义见 CacheEntry 注释
            variable_keys = tuple(sorted(variables.keys()))
            variable_types = {k: type(v).__name__ for k, v in variables.items()}
            existing = router._cache_db.find_by_instruction(
                router._env_class_type_key, instruction
            )
            if existing and existing.entry_id is not None:
                router._cache_db.update_entry(
                    router._env_class_type_key, existing.entry_id, success, code
                )
                for e in router._cache_entries:
                    if e.instruction_template == instruction:
                        e.last_used = datetime.now()
                        e.code = code
                        if success:
                            e.success_count += 1
                        else:
                            e.failure_count += 1
                        break
                return
            entry = CacheEntry(
                instruction_template=instruction,
                variable_keys=variable_keys,
                variable_types=variable_types,
                code=code,
                embedding=embedding,
                env_class_type=router._env_class_type_key,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
            )
            new_id = router._cache_db.add_entry(router._env_class_type_key, entry)
            entry.entry_id = new_id
            idx = len(router._cache_entries)
            router._cache_entries.append(entry)
            if embedding is not None:
                router._cache_faiss_entry_indices.append(idx)
                emb = embedding.astype(np.float32).reshape(1, -1).copy()
                faiss.normalize_L2(emb)
                if router._cache_faiss_index is None:
                    router._cache_faiss_index = faiss.IndexFlatIP(emb.shape[1])
                assert router._cache_faiss_index is not None
                router._cache_faiss_index.add(emb)

    async def on_final(self, context: AskContext) -> None:
        if context.success_data is None:
            return
        sd = context.success_data
        if (
            context.template_mode
            and not context.cache_entry
            and not context.is_observe_or_statistics
        ):
            await self._add_to_cache(
                self._router,
                context.instruction,
                context.variables,
                sd["code"],
                success=True,
            )


# --- Code Provider 责任链具体实现 ---


class PredefinedCodeProvider:
    """预定义代码提供者，优先级最高（<observe> / <statistics>）"""

    @property
    def name(self) -> str:
        return "predefined"

    async def get_code(
        self, context: AskContext, router: "CodeGenRouter"
    ) -> str | None:
        if not context.is_observe_or_statistics:
            return None
        if context.instruction_stripped == "<observe>":
            return router._observe_code if router._observe_code else None
        if context.instruction_stripped == "<statistics>":
            return router._statistics_code if router._statistics_code else None
        return None


class CacheCodeProvider:
    """模板缓存提供者，优先级第二"""

    @property
    def name(self) -> str:
        return "cache"

    @staticmethod
    async def _compute_embedding(
        router: "CodeGenRouter", text: str
    ) -> np.ndarray | None:
        try:
            async with router._embedding_cache_lock:
                if text in router._embedding_cache:
                    return router._embedding_cache[text]
            response = await aembedding(
                model=f"openai/{router._embedding_model}",
                input=[text],
                api_key=router._embedding_api_key,
                api_base=router._embedding_api_base,
            )
            if response and hasattr(response, "data") and len(response.data) > 0:
                emb = np.array(response.data[0]["embedding"], dtype=np.float32)
                async with router._embedding_cache_lock:
                    if len(router._embedding_cache) < 10000:
                        router._embedding_cache[text] = emb
                return emb
            return None
        except Exception as e:
            get_logger().warning(f"Failed to compute embedding: {e}")
            return None

    @staticmethod
    async def _lookup(
        router: "CodeGenRouter", instruction: str, variables: dict
    ) -> tuple[CacheEntry | None, str | None]:
        if not router._template_cache_enabled:
            return None, "template_cache_disabled"
        current_keys = set(variables.keys())
        # 精确匹配快速路径：指令串逐字符相同时无需 embedding/faiss，直接按
        # “代码必读变量 ⊆ 当前变量”判定能否复用。variable_keys 只是创建该
        # 条目时调用方传键的快照——多带无关键不该否决命中（曾把同指令
        # 6ms 级命中打成 6s 级全量 codegen），缺必读键更不该放行（缓存代码
        # max_retries=0，执行失败无回退）。同一指令可能有多条需求不同的条目，
        # 首条不满足须继续扫描。整段无 await：asyncio 单线程下原子，且
        # _cache_entries 仅追加，故无需持 _template_cache_lock。
        best_exact: CacheEntry | None = None
        saw_key_incompatible_candidate = False
        for entry in router._cache_entries:
            if entry.env_class_type != router._env_class_type_key:
                continue
            if entry.instruction_template != instruction:
                continue
            if not _entry_usable_with(entry, current_keys):
                saw_key_incompatible_candidate = True
                continue
            if best_exact is None or entry.success_count > best_exact.success_count:
                best_exact = entry
        if best_exact is not None:
            best_exact.last_used = datetime.now()
            return best_exact, None
        # 与 _add_to_cache 同理：embedding（含 HTTP）在锁外计算，_compute_embedding
        # 自带缓存与独立锁、并发安全；锁内只剩纯 CPU 的 faiss 检索，保持串行。
        emb = await CacheCodeProvider._compute_embedding(router, instruction)
        if emb is None:
            return None, "embedding_unavailable"
        async with router._template_cache_lock:
            best_match, best_sim = None, 0.0
            saw_compatible_candidate = False
            if router._cache_faiss_index and router._cache_faiss_entry_indices:
                query = np.asarray([emb], dtype=np.float32).copy()
                faiss.normalize_L2(query)
                k = min(32, router._cache_faiss_index.ntotal)
                scores, indices = router._cache_faiss_index.search(query, k)
                for score, idx in zip(scores[0], indices[0], strict=False):
                    if idx < 0:
                        break
                    entry_idx = router._cache_faiss_entry_indices[idx]
                    entry = router._cache_entries[entry_idx]
                    if entry.env_class_type != router._env_class_type_key:
                        continue
                    if not _entry_usable_with(entry, current_keys):
                        saw_key_incompatible_candidate = True
                        continue
                    saw_compatible_candidate = True
                    sim = float(score)
                    if (
                        sim >= router._template_cache_similarity_threshold
                        and sim > best_sim
                    ):
                        best_sim, best_match = sim, entry
            if best_match:
                best_match.last_used = datetime.now()
                return best_match, None
            if saw_compatible_candidate:
                return None, "below_similarity_threshold"
            if saw_key_incompatible_candidate:
                return None, "variable_keys_incompatible"
            return None, "no_similar_entry"

    async def get_code(
        self, context: AskContext, router: "CodeGenRouter"
    ) -> str | None:
        if (
            not router._template_cache_enabled
            or not context.template_mode
            or context.is_observe_or_statistics
        ):
            return None
        cache_entry, miss_reason = await self._lookup(
            router, context.instruction, context.variables
        )
        if cache_entry is not None:
            context.cache_entry = cache_entry
            return cache_entry.code
        context.cache_miss_reason = miss_reason
        get_logger().info(
            "Template cache miss: reason=%s instruction=%s",
            miss_reason,
            context.instruction[:100],
        )
        return None


class LLMCodegenProvider:
    """LLM 代码生成提供者，责任链最后一环，负责调用 LLM 生成代码"""

    @property
    def name(self) -> str:
        return "llm"

    @staticmethod
    def _build_prompt(
        router: "CodeGenRouter",
        instruction: str,
        ctx: dict,
        readonly: bool,
        kind: str | None = None,
    ) -> str:
        key = (readonly, kind)
        tools_pyi = router._tools_pyi_dict[key]
        template_note = ""
        if isinstance(ctx.get("variables"), dict) and ctx["variables"]:
            template_note = (
                "\n## Template Mode Hint\n"
                "- Runtime values are available in ctx['variables'].\n"
                "- Prefer reading changing values from ctx['variables'] instead of hard-coding literals.\n"
                "- This keeps the instruction reusable and improves router cache hits.\n"
            )
        return f"""# Code Generation Task

You write Python code that drives simulation environment tools on behalf of a
simulated agent, then reports what happened in plain language.

## Available Environment Modules and Tools
```python
{tools_pyi}
```
```python
modules = {router._modules!r}
```

## Agent Input
<instruction>{instruction}</instruction>
```python
ctx = {ctx!r}
```
{template_note}

## What to produce
Generate ONLY Python code — no markdown fences, no prose outside the code.
Start directly with Python statements. The code must:

1. Call the right environment tools to satisfy the instruction.
2. Store anything useful in the `results` dict and ALWAYS set
   `results['status']` at the very end: `'success'`, `'in_progress'`,
   `'fail'`, or `'error'`.
3. **Report the outcome with `print()` in clear natural language.**

## CRITICAL — your prints ARE the answer
The agent does not read raw variables. The text your code `print()`s is handed
to the agent verbatim as the result of its request (there is no separate
summary step). So write it the way you would explain the result to a person:

- Write complete, readable sentences. State what was asked, what you did, and
  what the outcome was.
- Pull the meaningful fields out of the tool responses and phrase them in
  natural language, quoting concrete values (ids, times, statuses) inline.
- Do NOT print raw dicts, reprs, or terse labels like `done` / `ok` /
  `response:`. Narrate instead.
- If the action failed or had no effect, say so plainly and give the reason.
- Keep it concise — a few sentences, not a paragraph.

## Status handling
- Inspect each tool's return value for a `status` field.
- Map an explicit status: success -> `results['status'] = 'success'`; error ->
  `'fail'`; still running -> `'in_progress'`.
- A tool that returns a plain value, or a dict without an error status, completed
  successfully: set `results['status'] = 'success'`.
- On failure also set `results['reason'] = "<short why>"`.

## Allowed building blocks
- In scope: `ctx`, `modules`, `results`, `print()`. Importable: collections,
  itertools, functools, operator, copy, decimal, fractions, statistics, string,
  re, datetime, json, math, random, numpy (as `np`).
- Follow each tool signature: use `await` for `async def` tools and call plain
  `def` tools directly. No dangerous operations.
- NEVER forget to set `results['status']` at the END of your code.

## Example (imitate the print style, not the exact tools)
response = await modules["MobilitySpace"].get_status(ctx["id"])
status = response.get("status", "success") if isinstance(response, dict) else "success"
if status == "success":
    loc = response.get("aoi_id")
    print(f"Checked the agent's status: it is currently at AOI {{loc}} and idle.")
    results["status"] = "success"
else:
    print("Could not read the agent's status from the environment.")
    results["status"] = "fail"
    results["reason"] = response.get("reason", "unknown")

Your generated code:"""

    @staticmethod
    def _build_error_message(previous_errors: list[str]) -> str:
        errors_text = "\n".join(
            f"- {i + 1}. {e}" for i, e in enumerate(previous_errors)
        )
        return f"""The code I generated failed during execution. Here's what went wrong:

## Errors
{errors_text}

Please analyze the errors and fix the code. Common issues: incorrect function/module names, wrong parameter types, async/await usage, type mismatches, missing imports, logic errors.

Please generate the corrected code:"""

    @staticmethod
    async def _call_llm(
        router: "CodeGenRouter", context: AskContext
    ) -> tuple[str, dict[str, int] | None]:
        try:
            response = await router.acompletion_with_system_prompt(
                model="coder", messages=context.dialog_history
            )
            raw = response.choices[0].message.content or ""  # type: ignore[union-attr]
            pattern = r"```(?:python)?\s*\n(.*?)```"
            matches = re.findall(pattern, raw, re.DOTALL)
            code = matches[0].strip() if matches else raw.strip()
            usage = getattr(response, "usage", None)
            token_usage = None
            if usage is not None:
                token_usage = {
                    "input_tokens": getattr(usage, "prompt_tokens", 0),
                    "output_tokens": getattr(usage, "completion_tokens", 0),
                }
            return code, token_usage
        except Exception as e:
            get_logger().error(f"{_get_debug_info('LLM代码生成失败')} - {e}")
            return "", None

    async def get_code(
        self, context: AskContext, router: "CodeGenRouter"
    ) -> str | None:
        if context.retry_count == 0:
            prompt = self._build_prompt(
                router,
                context.resolved_instruction,
                context.ctx,
                context.readonly,
                None,
            )
            context.dialog_history = [{"role": "user", "content": prompt}]
        else:
            if context.previous_code:
                context.dialog_history.append(
                    {"role": "assistant", "content": context.previous_code}
                )
            context.dialog_history.append(
                {
                    "role": "user",
                    "content": self._build_error_message(context.previous_errors),
                }
            )
        code, token_usage = await self._call_llm(router, context)
        if token_usage:
            context.token_usage_responses.append(token_usage)
        if code:
            # Layer 1 guard at generation time: ensure async tool calls use
            # ``await`` so the code stored in context.code (and thus in the
            # template cache) is already correct — no per-execution rewrite.
            code = _ensure_await_async_calls(code, _collect_async_tool_names(router))
        return code.strip() if code else None


# --- Pipeline 阶段具体实现 ---


class InitStage:
    """初始化：添加时间到 ctx，检查 env_modules"""

    async def process(self, context: AskContext, router: "CodeGenRouter") -> AskContext:
        router._add_current_time_to_ctx(context.ctx)
        if not router.env_modules:
            context.early_return = (
                context.ctx,
                "No environment modules available to handle the request.",
            )
        return context


class CodeStage:
    """
    代码获取（责任链）+ 验证 + 执行，含重试循环。
    Predefined -> Cache -> LLM；验证或执行失败时通过 LLM 重试。
    """

    @staticmethod
    async def _acquire_code(
        router: "CodeGenRouter", context: AskContext, retry_only: bool
    ) -> bool:
        providers = (
            router._code_provider_chain[-1:]
            if retry_only
            else router._code_provider_chain
        )
        for provider in providers:
            code = await provider.get_code(context, router)
            if code is not None:
                context.code = code
                context.code_source = provider.name
                return True
        return False

    @staticmethod
    def _validate_code_safety(router: "CodeGenRouter", code: str) -> tuple[bool, str]:
        violations = []
        try:
            tree = ast.parse(code, mode="exec")
            dangerous_functions = {
                "eval",
                "exec",
                "compile",
                "__import__",
                "open",
                "input",
            }

            def is_dangerous_module(name: str) -> bool:
                if name in router.ALLOWED_MODULES:
                    return False
                return name in router.DANGEROUS_MODULES or (
                    name.startswith("_") and name != "__future__"
                )

            def _is_truthy_constant(node: ast.expr) -> bool:
                """Check if an AST node is a compile-time truthy constant."""
                if isinstance(node, ast.Constant):
                    return bool(node.value)
                if isinstance(node, ast.Name) and node.id in {"True", "__debug__"}:
                    return True
                if isinstance(node, ast.Num):
                    return bool(node.n)
                return False

            def _loop_has_break(node: ast.AST) -> bool:
                """Check if a while/for loop body contains a reachable break."""
                for child in ast.walk(node):
                    if isinstance(child, ast.Break):
                        return True
                return False

            def _assigns_result_status(node: ast.stmt) -> bool:
                targets = node.targets if isinstance(node, ast.Assign) else []
                if isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                return any(
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "results"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "status"
                    for target in targets
                )

            for node in ast.walk(tree):
                if type(node) in router.FORBIDDEN_AST_NODES:
                    violations.append(f"Forbidden AST node type: {type(node).__name__}")
                elif isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Name)
                        and node.func.id in dangerous_functions
                    ):
                        violations.append(f"Dangerous function call: {node.func.id}()")
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in {
                        "eval",
                        "exec",
                        "compile",
                    }:
                        violations.append(f"Dangerous method call: {node.func.attr}()")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if is_dangerous_module(alias.name):
                            violations.append(f"Dangerous import: import {alias.name}")
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and is_dangerous_module(node.module)
                ):
                    violations.append(
                        f"Dangerous import: from {node.module} import ..."
                    )
                elif isinstance(node, ast.While) and _is_truthy_constant(node.test):
                    if not _loop_has_break(node):
                        violations.append(
                            "Potential infinite loop: while True without break"
                        )

            if not tree.body or not _assigns_result_status(tree.body[-1]):
                violations.append("Final statement must assign results['status']")
            if any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.lower() == "unknown"
                for node in ast.walk(tree)
            ):
                violations.append(
                    "Generated code must classify the outcome as success, fail, "
                    "in_progress, or error instead of unknown"
                )

            if violations:
                return (
                    False,
                    "Code safety check failed. Violations found:\n"
                    + "\n".join(f"- {v}" for v in violations),
                )
            return True, ""
        except SyntaxError as e:
            return False, f"Code syntax error: {e!s}"
        except Exception as e:
            return False, f"Code validation error: {e!s}"

    @staticmethod
    async def _execute_code(
        router: "CodeGenRouter", code: str, ctx: dict, readonly: bool
    ) -> dict[str, Any]:
        results = {}

        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name not in router.ALLOWED_MODULES:
                return None
            return __import__(name, globals, locals, fromlist, level)

        import collections
        import copy
        import decimal
        import fractions
        import functools
        import itertools
        import operator
        import statistics
        import string

        allowed_modules = {
            "collections": collections,
            "itertools": itertools,
            "functools": functools,
            "operator": operator,
            "copy": copy,
            "decimal": decimal,
            "fractions": fractions,
            "statistics": statistics,
            "string": string,
            "re": re,
            "datetime": datetime,
            "json": json,
            "math": math,
            "random": random,
            "numpy": np,
            "np": np,
        }
        restricted_builtins = {
            k: v for k, v in __builtins__.items() if k in router.ALLOWED_BUILTINS
        }
        restricted_builtins["__import__"] = safe_import
        # 每次执行注入独立的 print，不再全局替换 sys.stdout：async 生成代码在
        # await 环境工具期间让出事件循环，并发 ask 会互相换走进程级 stdout，
        # 恢复后 print 串进别人的 buffer（64 并发下实测串台）。生成代码无法
        # import sys（sys 在 DANGEROUS_MODULES），exec globals 又先于 builtins
        # 解析，print 一律走此注入路径，各自写入本次执行的 StringIO。
        captured_output = StringIO()

        def _sandbox_print(*args, sep=" ", end="\n", file=None, flush=False):
            print(
                *args,
                sep=sep,
                end=end,
                file=file if file is not None else captured_output,
                flush=flush,
            )

        exec_globals = {
            "__builtins__": restricted_builtins,
            "ctx": ctx,
            "modules": types.MappingProxyType(router._modules),
            "results": results,
            "print": _sandbox_print,
            **allowed_modules,
            "Exception": Exception,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "SyntaxError": SyntaxError,
            "NameError": NameError,
            "AttributeError": AttributeError,
            "IndexError": IndexError,
            "KeyError": KeyError,
        }
        exec_locals = {}
        try:
            is_async = "async" in code or "await" in code

            # Note: the Layer 1 AST await-guard now runs at code-generation
            # time (see LLMCodegenProvider.get_code and
            # _generate_initialization_code_with_retry), so the code stored
            # in _observe_code/_statistics_code and the template cache is
            # already corrected. No need to re-parse on every execution.

            if is_async:

                async def run_async():
                    indented = "\n".join(
                        "    " + line if line.strip() else ""
                        for line in code.split("\n")
                    )
                    async_code = f"async def _generated_main():\n{indented}"
                    exec(
                        compile(async_code, "<generated_async>", "exec"),
                        exec_globals,
                        exec_locals,
                    )
                    await exec_locals["_generated_main"]()

                await asyncio.wait_for(run_async(), timeout=10)
            else:
                deadline = time.monotonic() + 10

                def _timeout_tracer(frame, event, arg):
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "Code execution timeout: exceeded 10 seconds limit"
                        )
                    return _timeout_tracer

                compiled = compile(code, "<generated>", "exec")
                sys.settrace(_timeout_tracer)
                try:
                    exec(compiled, exec_globals, exec_locals)
                finally:
                    sys.settrace(None)
            output = captured_output.getvalue()
            print_outputs = [
                line.strip() for line in output.split("\n") if line.strip()
            ]
            return {
                "results": results,
                "output": output,
                "print_outputs": print_outputs,
                "success": True,
            }
        except TimeoutError:
            raise TimeoutError(
                "Code execution timeout: exceeded 10 seconds limit"
            ) from None
        except Exception as e:
            return {
                "results": results,
                "output": captured_output.getvalue(),
                "print_outputs": [],
                "error": str(e),
                "success": False,
            }

    async def process(self, context: AskContext, router: "CodeGenRouter") -> AskContext:
        if context.early_return:
            return context
        # <observe> / <statistics> flow through the normal codegen path using
        # the LLM-generated, init-time code from PredefinedCodeProvider
        # (_observe_code / _statistics_code). No hand-written builtin collection.
        max_retries = router.max_llm_call_retry if context.code is None else 0
        while context.retry_count <= max_retries:
            if context.code is None:
                ok = await self._acquire_code(
                    router, context, retry_only=bool(context.previous_errors)
                )
                if not ok:
                    context.retry_count += 1
                    context.previous_errors.append("Failed to generate code from LLM.")
                    context.previous_code = None
                    if context.retry_count > max_retries:
                        context.early_return = (
                            {},
                            "Failed to generate code after retries.",
                        )
                        return context
                    continue
                if context.code_source == "llm":
                    context.dialog_history.append(
                        {"role": "assistant", "content": context.code}
                    )

                assert context.code is not None  # set by _acquire_code when ok=True
                # AST 安全验证只用于拒绝首次 LLM 生成的代码；
                # 预定义（init 时生成）和缓存命中（首次已验证）的代码跳过。
                if context.code_source == "llm":
                    is_safe, safety_violation = self._validate_code_safety(
                        router, context.code
                    )
                    if not is_safe:
                        context.retry_count += 1
                        context.previous_code = context.code
                        context.previous_errors.append(safety_violation)
                        if context.retry_count > max_retries:
                            context.early_return = (
                                {},
                                f"Generated code failed safety check after retries: {safety_violation}",
                            )
                            return context
                        context.code = None
                        continue
            code = context.code
            if code is None:
                return context
            context.execution_attempted = True
            try:
                async with router._exec_lock_ctx():
                    execution_result = await self._execute_code(
                        router, code, context.ctx, context.readonly
                    )
            except Exception as e:
                execution_result = {
                    "success": False,
                    "error": str(e),
                    "results": {},
                    "print_outputs": [],
                    "output": "",
                }

            context.execution_result = execution_result
            # 代码执行后必须清理 ctx 和 results 中的 coroutine，以便序列化
            context.ctx = await clean_coroutines_from_results(context.ctx)
            if execution_result.get("results"):
                execution_result["results"] = await clean_coroutines_from_results(
                    execution_result["results"]
                )
            if not execution_result.get("success", False):
                error = execution_result.get("error", "Unknown error")
                context.retry_count += 1
                context.previous_code = code
                context.previous_errors.append(error)
                if context.retry_count > max_retries:
                    context.early_return = (
                        context.ctx,
                        f"Code execution failed after retries: {error}",
                    )
                    return context
                context.code = None
                continue

            print_outputs = execution_result.get("print_outputs", [])
            results = execution_result.get("results", {})
            status = results.get("status", "unknown")
            error = execution_result.get("error", "")
            process_text = "\n".join(print_outputs) if print_outputs else "无输出"
            if error:
                process_text += f"\n\nError: {error}"
            process_text = f"```\n{process_text}\n```"
            context.success_data = {
                "ctx": context.ctx,
                "instruction": context.resolved_instruction,
                "results": results,
                "process_text": process_text,
                "status": status,
                "error": error,
                "code": code,
            }
            context.results = results
            break
        return context


class SummaryStage:
    """生成最终答案"""

    async def process(self, context: AskContext, router: "CodeGenRouter") -> AskContext:
        if context.early_return:
            return context
        if not context.success_data:
            context.early_return = (
                {},
                "Failed to generate and execute code after all retries.",
            )
            return context
        sd = context.success_data
        context.results = sd["results"]

        if router._final_summary_enabled:
            final_answer, determined_status = await router.generate_final_answer(
                sd["ctx"],
                sd["instruction"],
                sd["results"],
                sd["process_text"],
                sd["status"],
                sd["error"],
            )
        else:
            final_answer = _build_deterministic_final_answer(router, sd)
            determined_status = sd["status"]

        context.results["status"] = determined_status
        context.final_answer = final_answer
        if determined_status == "unknown":
            context.results["status"] = "fail"
            context.results["reason"] = (
                "Generated code did not set results['status'], which is mandatory"
            )
        return context


class ObserveFinalStage:
    """流程结束后统一将 context 交给所有 observer 记录"""

    async def process(self, context: AskContext, router: "CodeGenRouter") -> AskContext:
        await router._notify_observers_final(context)
        return context


class CodeGenRouter(RouterBase):
    """
    代码生成式Router：通过生成Python代码的方式调用环境模块中的@tool标记的接口。

    工作流程：
    1. 收集所有环境模块的工具信息
    2. 使用类似 pyi 文件的 Python 代码格式向 LLM 提供环境模块描述和工具信息（含 pydantic BaseModel 与模块类定义）
    3. LLM 生成 Python 代码来调用工具
    4. 使用 AST 解析检查代码安全性
    5. 通过 compile 和 exec 执行代码，捕获打印输出
    6. 根据执行结果和打印输出生成最终响应
    """

    # 允许的内置函数
    ALLOWED_BUILTINS: ClassVar[set[str]] = {
        "print",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "tuple",
        "set",
        "range",
        "enumerate",
        "zip",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "sorted",
        "reversed",
        "any",
        "all",
        "isinstance",
        "type",
        "getattr",
        "hasattr",
        "dir",
    }

    # 禁止的AST节点类型（黑名单）
    FORBIDDEN_AST_NODES: ClassVar[set[type]] = {
        ast.ClassDef,  # 禁止定义类
        ast.Delete,  # 禁止del语句
        ast.Global,
        ast.Nonlocal,  # 禁止全局/非局部变量声明
        ast.With,
        ast.AsyncWith,  # 禁止with语句
        ast.Assert,  # 禁止assert
    }

    # 允许导入的模块白名单
    ALLOWED_MODULES: ClassVar[set[str]] = {
        "collections",
        "itertools",
        "functools",
        "operator",
        "copy",
        "decimal",
        "fractions",
        "statistics",
        "string",
        "re",
        "datetime",
        "json",
        "math",
        "random",
        "numpy",
        "np",  # numpy的别名
    }

    # 危险模块列表
    DANGEROUS_MODULES: ClassVar[set[str]] = {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pickle",
        "marshal",
        "ctypes",
        "socket",
        "urllib",
        "http",
        "ftplib",
        "smtplib",
        "__builtin__",
        "__builtins__",
        "builtins",
    }

    def __init__(
        self,
        env_modules: list[EnvBase],
        max_body_code_lines: int = 15,
        max_steps: int = 10,
        max_llm_call_retry: int = 10,
        replay_writer: Optional["ReplayWriter"] = None,
        final_summary_enabled: bool = False,
        code_format: str = "raw_code",
        # Template cache configuration
        template_cache_enabled: bool = True,  # 是否启用模板缓存
        template_cache_similarity_threshold: float = 0.85,  # 缓存相似度阈值
        template_cache_max_size: int = 1000,  # 单 env 类型最大缓存条目数
        template_cache_dir: str
        | None = None,  # 缓存数据库目录，None 则用 {Config.HOME_DIR}/codegen_router_cache
        # Injected serializable LLM clients. See RouterBase.
        llm_clients_spec: dict[str, Any] | None = None,
    ):
        super().__init__(
            env_modules=env_modules,
            max_steps=max_steps,
            max_llm_call_retry=max_llm_call_retry,
            replay_writer=replay_writer,
            llm_clients_spec=llm_clients_spec,
        )

        # Pre-generate all tools code in a dictionary: key is (readonly, kind)
        # kind can be None, "observe", "statistics", etc.
        self._tools_pyi_dict: dict[tuple[bool, str | None], str] = {}

        self._code_format = code_format
        self._max_body_code_lines = max_body_code_lines

        # Collect all tools info once and populate _tools_pyi_dict
        self._populate_tools_pyi_dict()

        self._modules = {module.name: module for module in self.env_modules}

        # observe / statistics 的初始化代码均由 LLM 在 init 中生成并缓存，每步复用。
        self._observe_code = ""
        self._statistics_code = ""

        # Flag to track if LLM code generation has been attempted
        self._llm_code_generated = False

        # ==================== Template缓存相关 ====================
        self._final_summary_enabled = final_summary_enabled
        self._template_cache_enabled = template_cache_enabled
        self._template_cache_similarity_threshold = template_cache_similarity_threshold
        self._template_cache_max_size = template_cache_max_size

        # Env class type 指纹，用于缓存隔离
        self._env_class_type_key = _get_env_class_type_key(env_modules)

        # 持久化缓存（pickle 文件，跨运行共用）
        cache_dir = template_cache_dir or os.path.join(
            Config.HOME_DIR, "codegen_router_cache"
        )
        cache_path = os.path.join(cache_dir, "cache.pkl")
        self._cache_dir = cache_dir  # 与 cache 同目录，用于保存 cache_stats.jsonl
        self._cache_db = TemplateCacheDB(
            cache_path=cache_path,
            embedding_dims=Config.EMBEDDING_DIMS,
            max_size_per_env=template_cache_max_size,
        )
        # 每步统计：用于计算 delta 并写入 JSONL
        self._cache_stats_jsonl_path = os.path.join(cache_dir, "cache_stats.jsonl")
        self._prev_step_stats: CacheStats | None = None
        self._step_index: int = 0
        self._run_id: str | None = None  # 在 init() 时设置，用于区分不同次模拟

        # 当前 env 的缓存集（从 DB 加载，在 init() 时填充）
        self._cache_entries: list[CacheEntry] = []
        self._cache_faiss_index: faiss.Index | None = None
        self._cache_faiss_entry_indices: list[int] = []
        self._template_cache_lock: asyncio.Lock = asyncio.Lock()

        # 缓存统计信息
        self._cache_stats = CacheStats()

        # Embedding缓存
        self._embedding_cache: dict[str, np.ndarray] = {}

        # Embedding模型配置（从Config获取）
        self._embedding_model = Config.EMBEDDING_MODEL
        self._embedding_api_key = Config.EMBEDDING_API_KEY
        self._embedding_api_base = Config.EMBEDDING_API_BASE
        self._embedding_dims = Config.EMBEDDING_DIMS

        # 并发锁：仅当代码执行会改动需要互斥的共享 env 状态时才需要串行。若所有 env 模块
        # 都声明 is_concurrency_safe()，则跳过该锁、env Ray actor 可并行 fan-out。
        self._execute_lock: asyncio.Lock = asyncio.Lock()
        self._exec_needs_lock: bool = not all(
            getattr(type(m), "is_concurrency_safe", lambda: False)()
            for m in self.env_modules
        )
        self._cache_stats_lock: asyncio.Lock = asyncio.Lock()
        self._embedding_cache_lock: asyncio.Lock = asyncio.Lock()

        # 观察者（缓存统计、instruction log、缓存写入）
        self._observers: list[AskObserver] = [
            CacheStatsObserver(self),
            CacheAddObserver(self),
        ]

        # Code 获取责任链：Predefined -> Cache -> LLM（LLM 在 pipeline 中单独处理）
        self._code_provider_chain: list[CodeProvider] = [
            PredefinedCodeProvider(),
            CacheCodeProvider(),
            LLMCodegenProvider(),
        ]

    def _exec_lock_ctx(self):
        """Return the exec serialization context manager (lock or a no-op).

        Args:
            None.

        Returns:
            An async context manager — the lock when any module is not
            concurrency-safe, otherwise a no-op (parallel exec allowed).
        """
        if self._exec_needs_lock:
            return self._execute_lock
        return nullcontext()

    def _get_tools_code(self, tools_info) -> str:
        if self._code_format == "raw_code":
            return self._format_tools_raw_code(tools_info)
        elif self._code_format == "trimmed":
            return self._format_tools_pyi_trimmed(tools_info, self._max_body_code_lines)
        elif self._code_format.startswith("ratio:"):
            ratio = float(self._code_format.split(":", 1)[1])
            return self._format_tools_pyi_ratio(tools_info, ratio)
        else:  # "pyi"
            return self._format_tools_pyi(tools_info, self._max_body_code_lines)

    def _populate_tools_pyi_dict(self) -> None:
        all_tools_info = self._collect_tools_info()
        all_tools_info = self._filter_tools_info(
            all_tools_info, readonly=None, kind=None
        )
        self._tools_pyi_dict[(False, None)] = self._get_tools_code(all_tools_info)

        readonly_tools_info = self._filter_tools_info(
            all_tools_info, readonly=True, kind=None
        )
        self._tools_pyi_dict[(True, None)] = self._get_tools_code(readonly_tools_info)

        readonly_observe_tools_info = self._filter_tools_info(
            all_tools_info, readonly=True, kind="observe"
        )
        if readonly_observe_tools_info:
            self._tools_pyi_dict[(True, "observe")] = self._get_tools_code(
                readonly_observe_tools_info
            )

        readonly_statistics_tools_info = self._filter_tools_info(
            all_tools_info, readonly=True, kind="statistics"
        )
        if readonly_statistics_tools_info:
            self._tools_pyi_dict[(True, "statistics")] = self._get_tools_code(
                readonly_statistics_tools_info
            )

    async def _notify_observers_final(self, context: AskContext) -> None:
        """流程结束后，将最终 context 交给所有观察者记录"""
        for obs in self._observers:
            await obs.on_final(context)

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> tuple[dict, str]:
        """
        使用代码生成方式处理指令。通过管道-过滤器架构执行。

        :param ctx: 上下文字典（在template模式下，应包含'variables'键）
        :param instruction: 指令字符串（在template模式下，为模板指令，包含{variable_name}占位符）
        :param readonly: 是否只读模式
        :param template_mode: 是否启用模板模式（启用后使用缓存机制）

        :returns: (ctx, answer) 元组
        """
        context = AskContext(
            ctx=ctx,
            instruction=instruction,
            readonly=readonly,
            template_mode=template_mode,
        )
        # Propagate OTel trace context to env modules for @tool tracing
        self.set_trace_context(trace_id, parent_span_id)
        # Bind per-ask trace context (ContextVar) so env-side LLM calls inside
        # CodeStage/SummaryStage emit llm.completion spans parented to this ask.
        agent_id = ctx.get("agent_id") if isinstance(ctx, dict) else None
        _trace_token = self._set_trace_context(trace_id, parent_span_id, agent_id)
        try:
            stages: list[PipelineStage] = [
                InitStage(),
                CodeStage(),  # 代码获取 + 验证 + 执行
                SummaryStage(),
                ObserveFinalStage(),  # 无论是否 early_return，最后统一交给 observer 记录
            ]
            for stage in stages:
                context = await stage.process(context, self)
        finally:
            self._reset_trace_context(_trace_token)
            self.clear_trace_context()
        if context.early_return:
            return context.early_return
        return context.results, context.final_answer

    async def init(self, start_datetime: datetime) -> bool:
        """
        Initialize the router with the start datetime and generate code using LLM.
        从本地缓存数据库加载当前 env 类型的缓存集，构建 FAISS 索引。

        :returns: 是否有 env 模块恢复了 checkpoint（透传自 ``RouterBase.init``）。
        """
        restored = await super().init(start_datetime)

        # 在async上下文中初始化锁
        get_logger().debug("Initialized instruction log lock")

        # 从持久化 DB 加载当前 env_class_type 的缓存，用于 embedding 相似度检索
        if self._template_cache_enabled:
            self._load_cache_from_db()

        # 为本次模拟生成 run_id，便于在 JSONL 中区分不同次模拟
        self._run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Generate code using LLM if not already done
        if not self._llm_code_generated:
            # Generate observe code using LLM (collects observe tools + narrates)
            if (True, "observe") in self._tools_pyi_dict:
                llm_observe_code = await self._generate_observe_code()
                if llm_observe_code:
                    self._observe_code = llm_observe_code
                    get_logger().info("Generated observe code using LLM")
                else:
                    raise ValueError("Failed to generate observe code")
            # Generate statistics code using LLM (using same logic as regular code generation)
            if (True, "statistics") in self._tools_pyi_dict:
                llm_statistics_code = await self._generate_statistics_code()
                if llm_statistics_code:
                    self._statistics_code = llm_statistics_code
                    get_logger().info("Generated statistics code using LLM")
                else:
                    raise ValueError("Failed to generate statistics code")
            self._llm_code_generated = True
        return restored

    async def step(self, tick: int, t: datetime):
        """Run forward one step for all simulation modules."""
        await super().step(tick, t)

    async def _generate_initialization_code_with_retry(
        self,
        instruction: str,
        ctx: dict,
        kind: str,
    ) -> str:
        """生成 observe/statistics 初始化代码，使用 LLMCodegenProvider 与 CodeStage。"""
        llm_provider = LLMCodegenProvider()
        code_stage = CodeStage()
        prompt = llm_provider._build_prompt(self, instruction, ctx, True, kind)
        dialog_history: list[AllMessageValues] = [{"role": "user", "content": prompt}]
        previous_code: str | None = None
        previous_errors: list[str] = []
        retry_count = 0

        while retry_count <= self.max_llm_call_retry:
            # 构造临时 context 供 _call_llm 使用
            tmp_ctx = AskContext(
                ctx=ctx, instruction=instruction, readonly=True, template_mode=False
            )
            tmp_ctx.dialog_history = dialog_history
            tmp_ctx.retry_count = retry_count
            tmp_ctx.previous_code = previous_code
            tmp_ctx.previous_errors = previous_errors

            code, token_usage = await llm_provider._call_llm(self, tmp_ctx)
            if token_usage:
                async with self._cache_stats_lock:
                    self._cache_stats.total_input_tokens += token_usage.get(
                        "input_tokens", 0
                    )
                    self._cache_stats.total_output_tokens += token_usage.get(
                        "output_tokens", 0
                    )

            if not code:
                previous_errors.append("Failed to generate code from LLM.")
                if retry_count >= self.max_llm_call_retry:
                    raise ValueError(f"Failed to generate {kind} code after retries.")
                retry_count += 1
                if previous_code:
                    dialog_history.append(
                        {"role": "assistant", "content": previous_code}
                    )
                previous_code = None
                dialog_history.append(
                    {
                        "role": "user",
                        "content": llm_provider._build_error_message(previous_errors),
                    }
                )
                continue

            # Layer 1 guard at generation time: ensure async tool calls use
            # ``await`` so the stored observe/statistics code is correct.
            code = _ensure_await_async_calls(code, _collect_async_tool_names(self))

            dialog_history.append({"role": "assistant", "content": code})
            is_safe, safety_violation = code_stage._validate_code_safety(self, code)
            if not is_safe:
                previous_errors.append(safety_violation)
                previous_code = code
                if retry_count >= self.max_llm_call_retry:
                    raise ValueError(
                        f"Generated {kind} code failed safety check after retries: {safety_violation}"
                    )
                retry_count += 1
                dialog_history.append(
                    {
                        "role": "user",
                        "content": llm_provider._build_error_message(previous_errors),
                    }
                )
                continue

            try:
                async with self._exec_lock_ctx():
                    execution_result = await code_stage._execute_code(
                        self, code, ctx, True
                    )
                if not execution_result.get("success", False):
                    previous_errors.append(
                        f"Execution failed: {execution_result.get('error', 'Unknown error')}"
                    )
                    previous_code = code
                    if retry_count >= self.max_llm_call_retry:
                        raise ValueError(
                            f"Generated {kind} code failed execution after retries."
                        )
                    retry_count += 1
                    dialog_history.append(
                        {
                            "role": "user",
                            "content": llm_provider._build_error_message(
                                previous_errors
                            ),
                        }
                    )
                    continue
            except Exception as e:
                previous_errors.append(f"Execution exception: {e!s}")
                previous_code = code
                if retry_count >= self.max_llm_call_retry:
                    raise ValueError(
                        f"Generated {kind} code failed execution after retries: {e!s}"
                    ) from e
                retry_count += 1
                dialog_history.append(
                    {
                        "role": "user",
                        "content": llm_provider._build_error_message(previous_errors),
                    }
                )
                continue

            return code.strip()
        raise ValueError(f"Failed to generate {kind} code after retries.")

    async def _generate_observe_code(self) -> str:
        """
        使用LLM生成观察代码，用于调用所有observe类型的工具并以自然语言汇报。
        使用与其他普通文本相同的代码生成逻辑，失败时通过多轮对话让LLM修正。

        :returns: 生成的Python代码字符串，如果生成失败则返回空字符串
        """
        get_logger().debug(f"{_get_debug_info('开始生成observe代码')}")

        if (True, "observe") not in self._tools_pyi_dict:
            get_logger().debug(f"{_get_debug_info('observe工具不存在')} - 跳过代码生成")
            return ""

        instruction = OBSERVE_INSTRUCTION
        ctx = {"id": 123}  # 测试执行用的最小上下文（observe 工具需要 agent id）
        return await self._generate_initialization_code_with_retry(
            instruction=instruction, ctx=ctx, kind="observe"
        )

    async def _generate_statistics_code(self) -> str:
        """
        使用LLM生成统计代码，用于调用所有statistics类型的工具。
        使用与其他普通文本相同的代码生成逻辑，失败时通过多轮对话让LLM修正。

        :returns: 生成的Python代码字符串，如果生成失败则返回空字符串
        """
        get_logger().debug(f"{_get_debug_info('开始生成statistics代码')}")

        if (True, "statistics") not in self._tools_pyi_dict:
            get_logger().debug(
                f"{_get_debug_info('statistics工具不存在')} - 跳过代码生成"
            )
            return ""

        instruction = STATISTICS_INSTRUCTION
        ctx = {}  # 测试执行用的最小上下文
        return await self._generate_initialization_code_with_retry(
            instruction=instruction, ctx=ctx, kind="statistics"
        )

    def _load_cache_from_db(self) -> None:
        """从本地缓存数据库加载当前 env_class_type 的缓存集，构建 FAISS 索引。"""
        entries, index, indices = self._cache_db.load_entries(self._env_class_type_key)
        self._cache_entries = entries
        self._cache_faiss_index = index
        self._cache_faiss_entry_indices = indices
        env_preview = self._env_class_type_key[:80] + (
            "..." if len(self._env_class_type_key) > 80 else ""
        )
        get_logger().info(
            f"Loaded {len(entries)} cache entries (env={env_preview}), FAISS index size: {len(indices)}"
        )

    def get_cache_stats(self) -> CacheStats:
        """
        获取缓存统计信息。

        :returns: CacheStats对象，包含所有缓存统计信息
        """
        # 同步方法无法用 async with，暂不加锁；step 中调用 get_cache_stats_summary 为最佳-effort
        return self._cache_stats

    def get_cache_stats_summary(self) -> str:
        """
        获取缓存统计信息的摘要字符串。

        :returns: 格式化的统计信息字符串
        """
        stats = self._cache_stats
        return f"""Cache Statistics Summary:
- Total Requests: {stats.request_count}
- Predefined Hits (observe/statistics): {stats.predefined_hit_count}
- Cache Hits: {stats.cache_hit_count}
- Cache Misses: {stats.cache_miss_count}
- Cache Hit Rate: {stats.cache_hit_rate:.2%}
- Total Input Tokens: {stats.total_input_tokens}
- Total Output Tokens: {stats.total_output_tokens}
- Average Input Tokens: {stats.avg_input_tokens:.2f}
- Average Output Tokens: {stats.avg_output_tokens:.2f}
- Code Execution Success: {stats.code_execution_success_count}
- Code Execution Failure: {stats.code_execution_failure_count}
- Code Execution Success Rate: {stats.code_execution_success_rate:.2%}
- Total Code Retries: {stats.total_code_retry_count}
- Average Code Retries per Request: {stats.avg_retry_count:.2f}
- Cache Size: {len(self._cache_entries)} entries (env={self._env_class_type_key[:60] + ("..." if len(self._env_class_type_key) > 60 else "")})"""

    async def clear_cache(self) -> None:
        """清空当前 env 的缓存（内存 + 持久化 DB）"""
        async with self._template_cache_lock:
            self._cache_db.clear_env_cache(self._env_class_type_key)
            self._cache_entries = []
            self._cache_faiss_index = None
            self._cache_faiss_entry_indices = []
            self._embedding_cache.clear()
            get_logger().info("Template cache cleared")

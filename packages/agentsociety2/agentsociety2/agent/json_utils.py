"""LLM 输出的 JSON 解析与修复。

流水线：严格解析（jiter/stdlib）→ 外壳剥离 → jsonmend → json_repair →
形状归一化；拒绝对非 JSON 散文的「引号发明」。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Literal

import jiter
import json_repair
import jsonmend

Expect = Literal["any", "object", "array", "object_or_array"]

_FENCE_RE = re.compile(
    r"```(?:json|JSON|js|javascript)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)
_TAG_RE = re.compile(
    r"<(?:tool_call|function(?:_call)?|tool_request)[^>]*>\s*(.*?)\s*</(?:tool_call|function(?:_call)?|tool_request)>",
    re.DOTALL | re.IGNORECASE,
)
_INVOKE_RE = re.compile(
    r"<invoke\b[^>]*>\s*(.*?)\s*</invoke>",
    re.DOTALL | re.IGNORECASE,
)
_PARAMS_RE = re.compile(
    r"<parameters>\s*(.*?)\s*</parameters>",
    re.DOTALL | re.IGNORECASE,
)
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
_CHATML_RE = re.compile(r"<\|[^|]+\|>")
_FINISH_RE = re.compile(
    r"finish\s*\(\s*(\{.*\})\s*\)\s*$",
    re.DOTALL | re.IGNORECASE,
)
_PROSE_JSON_RE = re.compile(r"[\{\[\(]")
_NAME_KEYS = ("name", "tool", "function")
_ARGS_KEYS = ("arguments", "args", "parameters")
_JSON_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _looks_jsonish(text: str) -> bool:
    if _PROSE_JSON_RE.search(text):
        return True
    stripped = text.strip()
    if stripped in {"True", "False", "None", "true", "false", "null"}:
        return True
    # 仅当 ``key: <JSON 形貌值>`` 时视为近 JSON，避免 ``TODO: …`` 被误判。
    match = re.match(r"^[A-Za-z_][\w-]*\s*:\s*(.+)$", stripped, flags=re.DOTALL)
    if not match:
        return False
    rest = match.group(1).strip()
    if rest.startswith(("{", "[", '"', "'")):
        return True
    if rest in {"True", "False", "None", "true", "false", "null"}:
        return True
    return bool(re.match(r"^-?\d+(\.\d+)?$", rest))


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def _strip_tool_tags(text: str) -> str:
    matches = list(_TAG_RE.finditer(text))
    if not matches:
        return text
    bodies = [m.group(1).strip() for m in matches if m.group(1).strip()]
    if not bodies:
        return text
    if len(bodies) == 1:
        return bodies[0]
    return "[" + ",".join(bodies) + "]"


def _strip_invoke(text: str) -> str:
    match = _INVOKE_RE.search(text)
    if not match:
        return text
    inner = match.group(1)
    params = _PARAMS_RE.search(inner) or _PARAMS_RE.search(text)
    if params:
        return params.group(1).strip()
    name_match = re.search(
        r'<invoke\b[^>]*\bname\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE
    )
    param_pairs = re.findall(
        r'<parameter\s+name\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</parameter>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if name_match and param_pairs:
        args = {k: v.strip() for k, v in param_pairs}
        for key, value in list(args.items()):
            low = value.lower()
            if low == "true":
                args[key] = True
            elif low == "false":
                args[key] = False
            elif low == "null":
                args[key] = None
        return json.dumps(
            {"name": name_match.group(1), "arguments": args},
            ensure_ascii=False,
        )
    return inner.strip()


def _strip_sse(text: str) -> str:
    payloads: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        payload = stripped[5:].strip()
        if payload and payload != "[DONE]":
            payloads.append(payload)
    if not payloads:
        return text
    if len(payloads) == 1:
        return payloads[0]
    return payloads[0]


def _strip_finish_call(text: str) -> str:
    match = _FINISH_RE.search(text.strip())
    if match:
        return match.group(1).strip()
    return text


def _strip_json_comments(text: str) -> str:
    """去掉 JSONC 行注释与块注释（字符串字面量内不处理）。"""
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    escape = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            i += 1
            continue
        if ch in {'"', "'"}:
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def preprocess(text: str) -> str:
    """剥离围栏、厂商标记、工具标签与 finish(...) 外壳。"""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    cleaned = _THINK_RE.sub("", cleaned)
    cleaned = _CHATML_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if "//" in cleaned or "/*" in cleaned:
        cleaned = _strip_json_comments(cleaned)
    if "data:" in cleaned:
        cleaned = _strip_sse(cleaned)
    if "```" in cleaned:
        cleaned = _strip_fences(cleaned)
    lowered = cleaned.lower()
    if "<invoke" in lowered:
        cleaned = _strip_invoke(cleaned)
    elif "<" in cleaned and ("tool" in lowered or "function" in lowered):
        cleaned = _strip_tool_tags(cleaned)
    cleaned = _strip_finish_call(cleaned)
    return cleaned.strip()


def _try_strict(text: str) -> Any | None:
    raw = text.encode("utf-8")
    try:
        return jiter.from_json(raw)
    except Exception:
        pass
    try:
        return json.loads(text)
    except Exception:
        return None


def _sanitize(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_sanitize(value), ensure_ascii=False, allow_nan=False)


def _string_literals(text: str) -> Counter[str]:
    """Count intact JSON string literals, ignoring malformed fragments."""
    literals: Counter[str] = Counter()
    for match in _JSON_STRING_RE.finditer(text):
        try:
            literals[json.loads(match.group())] += 1
        except json.JSONDecodeError:
            continue
    return literals


def _repair_text(text: str) -> str | None:
    """Prefer a repair that preserves intact input strings, including keys.

    jsonmend can absorb a closing quote into a value when a comma is missing.
    Only consult the second engine when the first changes an intact literal;
    clean JSON and repairs preserving all literals keep their fast paths.
    This is a conservative tie-breaker, not a semantic correctness guarantee.
    """
    original_literals = _string_literals(text)
    best: str | None = None
    best_loss = math.inf
    for engine in (jsonmend.repair_json, json_repair.repair_json):
        try:
            repaired = engine(text)
            if not isinstance(repaired, str) and repaired is not None:
                repaired = _dumps(repaired)
            if not isinstance(repaired, str) or not repaired.strip():
                continue
            json.loads(repaired)
        except Exception:
            continue
        loss = sum((original_literals - _string_literals(repaired)).values())
        if loss == 0:
            return repaired
        if loss < best_loss:
            best, best_loss = repaired, loss
    return best


def _is_quoted_prose(original: str, value: Any) -> bool:
    """非 JSON 形貌输入被修成 JSON 字符串（含空串）时视为发明，应拒绝。"""
    if not isinstance(value, str):
        return False
    return not _looks_jsonish(original)


def _expect_ok(value: Any, expect: Expect) -> bool:
    if expect == "any":
        return True
    if expect == "object":
        return isinstance(value, dict)
    if expect == "array":
        return isinstance(value, list)
    return isinstance(value, (dict, list))


def _looks_like_tool_call(value: dict[str, Any]) -> bool:
    has_args = any(key in value for key in _ARGS_KEYS)
    has_alias_name = any(
        key in value and isinstance(value[key], str) for key in ("tool", "function")
    )
    has_name = isinstance(value.get("name"), str)
    return has_args and (has_name or has_alias_name)


def _normalize_tool_shape(value: Any) -> Any:
    """将工具调用上的 tool/function/args 别名归一为 name/arguments。

    不改写 plan 步骤等仅含 ``tool`` 字段、但无 arguments/args 的对象。
    """
    if isinstance(value, list):
        return [_normalize_tool_shape(item) for item in value]
    if not isinstance(value, dict):
        return value

    if not _looks_like_tool_call(value):
        return {key: _normalize_tool_shape(item) for key, item in value.items()}

    out = dict(value)
    if "name" not in out:
        for key in ("tool", "function"):
            if key in out and isinstance(out[key], str):
                out["name"] = out.pop(key)
                break
    if "arguments" not in out:
        for key in ("args", "parameters"):
            if key in out:
                out["arguments"] = out.pop(key)
                break

    arguments = out.get("arguments")
    if isinstance(arguments, str):
        stripped = arguments.strip()
        if stripped.startswith(("{", "[")):
            out["arguments"] = loads_llm_json(
                arguments, expect="any", normalize_tools=False
            )
    return out


def loads_llm_json(
    text: str,
    *,
    expect: Expect = "any",
    normalize_tools: bool = True,
) -> Any:
    """解析并修复 LLM 产出的 JSON 文本。

    :param text: 原始模型输出（可含围栏、标签、轻微截断）。
    :param expect: 期望顶层类型；不满足时抛 ``ValueError`` 。
    :param normalize_tools: 是否归一化工具调用键名。
    :returns: Python 对象。
    :raises ValueError: 无法可靠解析，或结果仅为散文引号包装。
    """
    if text is None:
        raise ValueError("LLM JSON input is None")
    original = text
    if not original.strip():
        raise ValueError("LLM JSON input is empty")

    # Valid JSON may itself contain literal protocol tags or code fences in a
    # message. Parse it before stripping wrappers, which would mutate values.
    original_strict = _try_strict(original)
    if original_strict is not None and _expect_ok(original_strict, expect):
        value = _sanitize(original_strict)
        return _normalize_tool_shape(value) if normalize_tools else value

    candidates = [original]
    prepared = preprocess(original)
    if prepared and prepared != original:
        candidates.insert(0, prepared)

    last_error = "repair-empty"
    for candidate in candidates:
        strict = _try_strict(candidate) if candidate != original else original_strict
        if strict is not None:
            value = _sanitize(strict)
            if _expect_ok(value, expect):
                if normalize_tools:
                    value = _normalize_tool_shape(value)
                return value
            last_error = "shape"
            continue

        repaired = _repair_text(candidate)
        if repaired is None:
            continue
        try:
            value = json.loads(repaired)
        except json.JSONDecodeError:
            try:
                value = json_repair.loads(candidate)
            except Exception:
                last_error = "parse-repaired"
                continue
        value = _sanitize(value)
        if _is_quoted_prose(original.strip(), value):
            raise ValueError("refused quoted prose as JSON")
        if not _expect_ok(value, expect):
            last_error = "shape"
            continue
        if normalize_tools:
            value = _normalize_tool_shape(value)
        return value

    if not _looks_jsonish(original):
        raise ValueError("non-jsonish prose")
    raise ValueError(f"failed to parse LLM JSON: {last_error}")


def jr_parse_from_llm(content: str) -> Any:
    """从 LLM 响应文本抽取并解析 JSON（``loads_llm_json`` 别名）。"""
    return loads_llm_json(content, expect="any")


def jr_or_json(text: str) -> Any:
    """宽松解析 LLM JSON（``loads_llm_json`` 别名）。"""
    return loads_llm_json(text, expect="any")

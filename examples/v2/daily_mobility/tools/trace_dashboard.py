"""OTel Trace Flame Graph Viewer for AgentSociety2.

Usage:
    TRACE_RUN_DIR=examples/v2/daily_mobility/tmp/run \
        uv run streamlit run examples/v2/daily_mobility/tools/trace_dashboard.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

SPAN_COLORS = {
    "agent.init": "#6c8cff",
    "agent.step": "#5b7bf5",
    "llm.completion": "#4ecdc4",
    "react.loop": "#f59e0b",
    "react.turn": "#fb923c",
    "react.tool": "#f97316",
    "workspace.write_text": "#8b5cf6",
    "workspace.read_text": "#a78bfa",
    "skill.visibility.set": "#ec4899",
    "skill.load_doc": "#f472b6",
}
DEFAULT_COLOR = "#64748b"

# Attributes that contain long text — render separately, not in the table
RICH_ATTRS = {
    "react.thought",
    "output.summary",
    "input.summary",
    "output.summary.observation",
}

# Order for displaying key attributes in the detail table
ATTR_DISPLAY_ORDER = [
    "agent.id", "agent.tick", "event.type", "event.sequence", "step.count",
    "react.action", "react.turn", "react.end_reason", "react.max_turns",
    "react.tool_ok", "result.ok",
    "llm.model", "input.message_count", "output.chars", "llm.retry",
    "operation.type",
    "workspace.path", "result.bytes", "result.size",
    "skill.id", "skill.visible_count", "skill.discovery_sources",
    "workspace", "profile.keys", "workspace.seed_count", "world.description_chars",
]


@dataclass
class Span:
    agent_id: int
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    status: str
    start_ms: float
    end_ms: float
    duration_ms: float
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def color(self) -> str:
        return SPAN_COLORS.get(self.name, DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_jsonl(path: Path) -> list[Span]:
    spans: list[Span] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        attrs = raw.get("attributes") or {}
        start = float(raw.get("start_time_unix_nano", 0)) / 1e6
        end = float(raw.get("end_time_unix_nano", 0)) / 1e6
        spans.append(
            Span(
                agent_id=raw.get("resource", {}).get("agent.id", attrs.get("agent.id", 0)),
                trace_id=raw.get("trace_id", ""),
                span_id=raw.get("span_id", ""),
                parent_span_id=raw.get("parent_span_id") or None,
                name=raw.get("name", ""),
                status=raw.get("status", {}).get("code", "ok"),
                start_ms=start,
                end_ms=end,
                duration_ms=max(0, end - start),
                attrs=attrs,
            )
        )
    return spans


def discover_spans(run_dir: Path) -> list[Span]:
    all_spans: list[Span] = []
    for p in sorted(run_dir.glob("agents/agent_*/.runtime/events.jsonl")):
        all_spans.extend(parse_jsonl(p))
    if not all_spans:
        for p in sorted(run_dir.glob("*.jsonl")):
            all_spans.extend(parse_jsonl(p))
    return all_spans


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_dur(ms: float) -> str:
    if ms < 1_000:
        return f"{ms:.0f} ms"
    if ms < 60_000:
        return f"{ms / 1_000:.1f} s"
    return f"{ms / 60_000:.1f} min"


def fmt_ts(ms: float) -> str:
    """Convert unix-ms to human readable datetime."""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%H:%M:%S.") + f"{ms % 1000:.0f}"
    except (OSError, OverflowError, ValueError):
        return f"{ms:.0f}"


def fmt_val(v: Any) -> str:
    if isinstance(v, bool):
        return "✅ true" if v else "❌ false"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, indent=2)
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def build_tree(spans: list[Span]) -> list[tuple[int, Span]]:
    """Flatten spans into DFS order with depth."""
    by_id = {s.span_id: s for s in spans}
    children_map: dict[str, list[Span]] = {}
    roots: list[Span] = []
    for s in spans:
        if not s.parent_span_id or s.parent_span_id not in by_id:
            roots.append(s)
        else:
            children_map.setdefault(s.parent_span_id, []).append(s)

    rows: list[tuple[int, Span]] = []

    def walk(sp: Span, depth: int) -> None:
        rows.append((depth, sp))
        for kid in sorted(children_map.get(sp.span_id, []), key=lambda x: x.start_ms):
            walk(kid, depth + 1)

    for r in sorted(roots, key=lambda x: x.start_ms):
        walk(r, 0)
    return rows


# ---------------------------------------------------------------------------
# Hover text builder
# ---------------------------------------------------------------------------

_HOVER_WRAP = 72          # chars per line before wrapping
_HOVER_MAX_FIELD = 300    # max chars for a single field
_HOVER_MAX_TOTAL = 1200   # max total hover text length


def _truncate(text: str, limit: int = _HOVER_MAX_FIELD) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _wrap(text: str, width: int = _HOVER_WRAP) -> str:
    """Insert ``<br>`` to keep lines within *width* characters."""
    if len(text) <= width:
        return text
    out: list[str] = []
    while text:
        if len(text) <= width:
            out.append(text)
            break
        # try to break at last space within width
        cut = text[:width].rfind(" ")
        if cut <= width // 2:   # no good break point — hard cut
            cut = width
        out.append(text[:cut])
        text = text[cut:].lstrip()
    return "<br>".join(out)


def _extract_observation(output_summary: Any) -> str:
    """Extract observation text from output.summary (various shapes)."""
    if isinstance(output_summary, dict):
        obs = output_summary.get("observation")
        if isinstance(obs, str):
            return obs
        # fallback: first string value
        for v in output_summary.values():
            if isinstance(v, str) and len(v) > 20:
                return v
    if isinstance(output_summary, str):
        return output_summary
    return ""


def build_hover(sp: Span) -> str:
    """Build rich hover text for a span bar, with line wrapping."""
    a = sp.attrs
    lines: list[str] = []

    # Header
    status = "✅" if sp.status == "ok" else "❌"
    lines.append(f"<b>{sp.name}</b>  {status}  {fmt_dur(sp.duration_ms)}")

    # ── Per-type detail ─────────────────────────────
    name = sp.name

    if name == "agent.init":
        ws = str(a.get("workspace", "—"))
        lines.append(f"workspace: {_wrap(ws, 60)}")
        lines.append(f"skills visible: {a.get('skill.visible_count', '—')}")
        lines.append(f"workspace seed files: {a.get('workspace.seed_count', '—')}")
        lines.append(f"world desc chars: {a.get('world.description_chars', '—')}")

    elif name == "agent.step":
        inp = a.get("input.summary")
        if isinstance(inp, dict):
            lines.append(f"tick: {inp.get('tick', '—')}  time: {inp.get('time', '—')}")
        lines.append(f"step #{a.get('step.count', '?')}")
        lines.append(f"skills visible: {a.get('skill.visible_count', '—')}")
        out = a.get("output.summary")
        if isinstance(out, dict) and out.get("result"):
            lines.append("<b>result:</b>")
            lines.append(_wrap(_truncate(out["result"], 200)))

    elif name == "react.loop":
        lines.append(f"max turns: {a.get('react.max_turns', '—')}")
        lines.append(f"end reason: <b>{a.get('react.end_reason', '—')}</b>")
        out = a.get("output.summary")
        if isinstance(out, dict) and out.get("final"):
            lines.append("<b>final:</b>")
            lines.append(_wrap(_truncate(out["final"], 200)))

    elif name == "react.turn":
        lines.append(f"turn #{a.get('react.turn', '?')}  action: <b>{a.get('react.action', '—')}</b>")
        thought = a.get("react.thought")
        if thought:
            lines.append("<b>thought:</b>")
            lines.append(_wrap(_truncate(thought, 300)))
        tool_ok = a.get("react.tool_ok")
        if tool_ok is not None:
            lines.append(f"tool_ok: {'✅' if tool_ok else '❌'}")

    elif name == "react.tool":
        lines.append(f"action: <b>{a.get('react.action', '—')}</b>")
        lines.append(f"result: {'✅ ok' if a.get('result.ok') else '❌ fail' if a.get('result.ok') is False else '—'}")
        obs = _extract_observation(a.get("output.summary"))
        if obs:
            lines.append("<b>observation:</b>")
            lines.append(_wrap(_truncate(obs, 300)))

    elif name == "llm.completion":
        lines.append(f"model: <b>{a.get('llm.model', '—')}</b>")
        lines.append(f"input msgs: {a.get('input.message_count', '—')}  output chars: {a.get('output.chars', '—')}")
        if a.get("llm.retry"):
            lines.append("⚠️ retry")

    elif name.startswith("workspace."):
        lines.append(f"path: {a.get('workspace.path', '—')}")
        lines.append(f"bytes: {a.get('result.bytes', a.get('result.size', '—'))}")

    elif name.startswith("skill."):
        if a.get("skill.id"):
            lines.append(f"skill: {a['skill.id']}")
        lines.append(f"visible: {a.get('skill.visible_count', '—')}")

    # ── Remaining interesting attrs ─────────────────
    shown = {
        "operation.type", "event.sequence",
        "workspace", "profile.keys", "workspace.seed_count", "world.description_chars",
        "agent.id", "agent.tick", "event.type", "step.count",
        "react.action", "react.turn", "react.end_reason", "react.max_turns",
        "react.tool_ok", "react.thought",
        "llm.model", "input.message_count", "output.chars", "llm.retry",
        "workspace.path", "result.bytes", "result.size", "result.ok",
        "skill.id", "skill.visible_count", "skill.discovery_sources",
        "output.summary", "input.summary",
    }
    extra = [f"{k}={v}" for k, v in sorted(a.items()) if k not in shown and v is not None]
    if extra:
        lines.append(_wrap("  ".join(extra[:4])))

    text = "<br>".join(lines)
    if len(text) > _HOVER_MAX_TOTAL:
        text = text[:_HOVER_MAX_TOTAL] + "…"
    return text


# ---------------------------------------------------------------------------
# Flame chart
# ---------------------------------------------------------------------------

def build_flame(spans: list[Span]) -> go.Figure:
    if not spans:
        return go.Figure()

    rows = build_tree(spans)
    origin = min(s.start_ms for s in spans)
    max_depth = max(d for d, _ in rows) if rows else 0

    bar_traces = []
    for depth, sp in rows:
        x0 = sp.start_ms - origin
        w = max(sp.duration_ms, 0.5)

        bar_traces.append(go.Bar(
            y=[-depth],
            x=[w],
            base=[x0],
            orientation="h",
            marker_color=sp.color,
            marker_line_width=0.5,
            marker_line_color="#1a1d27",
            text=sp.name if w > 8 else "",
            textposition="inside",
            textfont_size=11,
            textfont_color="#fff",
            hovertext=build_hover(sp),
            hoverinfo="text",
            showlegend=False,
            customdata=[sp.span_id],
        ))

    fig = go.Figure(data=bar_traces)

    seen: dict[str, str] = {}
    for _, sp in rows:
        if sp.name not in seen:
            seen[sp.name] = sp.color

    fig.update_layout(
        barmode="overlay",
        height=max(280, 36 * (max_depth + 1) + 60),
        margin={"l": 8, "r": 8, "t": 40, "b": 32},
        plot_bgcolor="#1a1d27",
        paper_bgcolor="#1a1d27",
        font_color="#e4e6f0",
        xaxis={"title_text": "Time (ms)", "gridcolor": "#2e3347", "zeroline": False},
        yaxis={"visible": False},
        hoverlabel={
            "bgcolor": "#242834",
            "bordercolor": "#3e4460",
            "font_color": "#e4e6f0",
            "font_size": 13,
            "font_family": "monospace",
        },
    )

    for i, (name, color) in enumerate(seen.items()):
        fig.add_annotation(
            xref="paper", yref="paper",
            x=0.01 + i * 0.13, y=1.07,
            text=f"■ {name}",
            showarrow=False,
            font={"size": 11, "color": color},
        )

    return fig


# ---------------------------------------------------------------------------
# Detail panel
# ---------------------------------------------------------------------------

def render_span_detail(sp: Span, all_trace_spans: list[Span]) -> None:
    """Render full span detail panel."""

    # -- Header --
    status_icon = "✅" if sp.status == "ok" else "❌"
    st.markdown(f"### {status_icon} `{sp.name}`")
    st.caption(f"span_id: `{sp.span_id}`  ·  trace_id: `{sp.trace_id}`")

    # -- Timing --
    c1, c2, c3 = st.columns(3)
    c1.metric("Duration", fmt_dur(sp.duration_ms))
    c2.metric("Start", fmt_ts(sp.start_ms))
    c3.metric("End", fmt_ts(sp.end_ms))

    if sp.parent_span_id:
        parent = next((s for s in all_trace_spans if s.span_id == sp.parent_span_id), None)
        if parent:
            st.caption(f"⬆ Parent: `{parent.name}` ({fmt_dur(parent.duration_ms)}) — `{sp.parent_span_id}`")

    st.divider()

    # -- Rich text fields (thought, summary, etc.) --
    rich_displayed = set()

    # react.thought
    thought = sp.attrs.get("react.thought")
    if thought:
        rich_displayed.add("react.thought")
        st.markdown("**💭 Agent Thought**")
        st.info(thought)

    # output.summary (can be dict or string)
    out_sum = sp.attrs.get("output.summary")
    if out_sum:
        rich_displayed.add("output.summary")
        st.markdown("**📤 Output Summary**")
        if isinstance(out_sum, dict):
            for k, v in out_sum.items():
                st.markdown(f"**{k}:**")
                if isinstance(v, str) and len(v) > 80:
                    st.code(v, language=None)
                else:
                    st.write(v)
        elif isinstance(out_sum, str):
            st.code(out_sum, language=None)
        else:
            st.write(out_sum)

    # input.summary
    in_sum = sp.attrs.get("input.summary")
    if in_sum:
        rich_displayed.add("input.summary")
        st.markdown("**📥 Input Summary**")
        if isinstance(in_sum, dict):
            st.json(in_sum)
        else:
            st.code(str(in_sum), language=None)

    # react.end_reason final output (inside react.loop)
    final = sp.attrs.get("output.summary", {}).get("final") if isinstance(sp.attrs.get("output.summary"), dict) else None
    if final:
        rich_displayed.add("output.summary")
        st.markdown("**🏁 Final Output**")
        st.code(final, language=None)

    if rich_displayed:
        st.divider()

    # -- All attributes table --
    st.markdown("**📋 All Attributes**")

    # Ordered display
    displayed_keys = set()
    table_rows = []
    for key in ATTR_DISPLAY_ORDER:
        if key in sp.attrs:
            displayed_keys.add(key)
            v = sp.attrs[key]
            table_rows.append({"Key": key, "Value": fmt_val(v)})

    # Remaining attrs
    for key in sorted(sp.attrs):
        if key not in displayed_keys:
            v = sp.attrs[key]
            table_rows.append({"Key": key, "Value": fmt_val(v)})

    if table_rows:
        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Key": st.column_config.TextColumn(width="small"),
                "Value": st.column_config.TextColumn(width="large"),
            },
        )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Trace Flame Graph", page_icon="🔥", layout="wide")
    st.title("🔥 Trace Flame Graph")
    st.caption("AgentSociety2 — OpenTelemetry Span Viewer")

    # -- Sidebar --
    with st.sidebar:
        st.header("📁 Data")
        run_dir = Path(
            os.environ.get("TRACE_RUN_DIR") or Path(__file__).resolve().parents[1] / "tmp/run"
        ).expanduser().resolve()
        st.caption(f"Run directory: {run_dir}")
        if not run_dir.is_dir():
            st.error(f"Not found: {run_dir}")
            st.stop()

        with st.spinner("Loading..."):
            all_spans = discover_spans(run_dir)
        if not all_spans:
            st.error("No events.jsonl found")
            st.stop()

        st.success(f"**{len(all_spans)}** spans loaded")

        st.divider()
        st.header("🎛️ Filter")

        agent_ids = sorted({s.agent_id for s in all_spans})
        sel_agents = st.multiselect("Agents", agent_ids, default=agent_ids, format_func=lambda x: f"Agent {x}")

        trace_ids = sorted({s.trace_id for s in all_spans if s.agent_id in sel_agents})
        sel_traces = st.multiselect("Traces", trace_ids, default=trace_ids)

    spans = [s for s in all_spans if s.agent_id in sel_agents and s.trace_id in sel_traces]
    if not spans:
        st.warning("No spans match filter.")
        st.stop()

    # -- Top stats --
    c1, c2, c3 = st.columns(3)
    c1.metric("Spans", len(spans))
    c2.metric("Traces", len(sel_traces))
    c3.metric("Wall Time", fmt_dur(max(s.end_ms for s in spans) - min(s.start_ms for s in spans)))
    st.divider()

    # -- Per-trace sections --
    for trace_id in sel_traces:
        trace_spans = [s for s in spans if s.trace_id == trace_id]
        if not trace_spans:
            continue

        t_min = min(s.start_ms for s in trace_spans)
        t_max = max(s.end_ms for s in trace_spans)
        agent_id = trace_spans[0].agent_id

        st.subheader(f"Agent {agent_id} — `{trace_id}`")
        st.caption(f"{len(trace_spans)} spans · wall time {fmt_dur(t_max - t_min)}")

        # Flame chart
        fig = build_flame(trace_spans)
        st.plotly_chart(fig, use_container_width=True)

        # -- Span selector + detail --
        tree_rows = build_tree(trace_spans)
        by_sid = {s.span_id: s for s in trace_spans}

        # Build label for selectbox with tree indentation
        span_options = []
        span_labels = {}
        for depth, sp in tree_rows:
            indent = "　" * depth + ("└ " if depth > 0 else "")
            dur_str = fmt_dur(sp.duration_ms)
            action = sp.attrs.get("react.action", "")
            suffix = f" ({action})" if action else ""
            label = f"{indent}{sp.name}{suffix}  [{dur_str}]"
            span_options.append(sp.span_id)
            span_labels[sp.span_id] = label

        selected_sid = st.selectbox(
            "🔍 Select a span to inspect",
            options=span_options,
            format_func=span_labels.__getitem__,
            key=f"sel_{trace_id}",
        )

        if selected_sid and selected_sid in by_sid:
            render_span_detail(by_sid[selected_sid], trace_spans)

        st.divider()


if __name__ == "__main__":
    main()

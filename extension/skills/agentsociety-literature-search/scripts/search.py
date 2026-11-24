#!/usr/bin/env python3
"""Literature search CLI script"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def _workspace_root() -> Path:
    raw = os.environ.get("AGENTSOCIETY_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".env").exists() or (candidate / ".agentsociety").exists():
            return candidate
    return here.parents[4]


workspace_root = _workspace_root()
env_file = workspace_root / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

sys.path.insert(0, str(workspace_root / "packages" / "agentsociety2"))


def _import_literature_api():
    """按需导入 literature API，保证未安装时仍能解析 --help。"""
    try:
        from agentsociety2.skills.literature import (
            search_literature_and_save,
            format_search_results,
            generate_summary,
        )
        from agentsociety2.config import get_llm_router
    except ImportError as exc:
        raise SystemExit(
            "agentsociety2 is not available in the current Python interpreter. "
            "Install it (e.g. `uv sync` from the workspace root) and retry. "
            f"Original error: {exc}"
        )
    return {
        "search_literature_and_save": search_literature_and_save,
        "format_search_results": format_search_results,
        "generate_summary": generate_summary,
        "get_llm_router": get_llm_router,
    }


async def main():
    parser = argparse.ArgumentParser(description="Search academic literature")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of articles (default: 10)"
    )
    parser.add_argument(
        "--year-from", type=int, default=None, help="Filter by year (start)"
    )
    parser.add_argument(
        "--year-to", type=int, default=None, help="Filter by year (end)"
    )
    parser.add_argument("--workspace", default=".", help="Workspace path")
    parser.add_argument(
        "--multi-query",
        action="store_true",
        help="Enable multi-query mode (split complex queries into subtopics)",
    )

    args = parser.parse_args()

    api = _import_literature_api()
    search_literature_and_save = api["search_literature_and_save"]
    format_search_results = api["format_search_results"]
    generate_summary = api["generate_summary"]
    get_llm_router = api["get_llm_router"]

    workspace_path = Path(args.workspace).resolve()
    router = get_llm_router("default")

    result = await search_literature_and_save(
        query=args.query,
        workspace_path=workspace_path,
        router=router,
        limit=args.limit,
        year_from=args.year_from,
        year_to=args.year_to,
        enable_multi_query=args.multi_query,
    )

    if result.get("success"):
        content = format_search_results(
            result["articles"],
            result["total"],
            result["query"],
        )

        # Generate summary
        try:
            summary = await generate_summary(
                args.query,
                result["articles"],
                result["total"],
                router,
            )
            content += "\n\n" + summary
        except Exception as e:
            print(f"Warning: Failed to generate summary: {e}")

        saved_files = result.get("saved_files", [])
        full_text_stats = result.get("full_text_stats") or {}
        index_path = workspace_path / "papers" / "literature_index.json"
        if saved_files:
            content += (
                "\n\n## Saved Artifacts\n"
                f"- Literature index: `{index_path}`\n"
                f"- Markdown notes saved: {len(saved_files)}\n"
                "- Use `@papers/<note>.md` references for Claude/Agent reading.\n"
            )
            if full_text_stats:
                content += (
                    "- Open-access PDF download: "
                    f"downloaded={full_text_stats.get('downloaded', 0)}, "
                    f"no_candidate={full_text_stats.get('no_candidate', 0)}, "
                    f"failed={full_text_stats.get('failed', 0)}, "
                    f"skipped={full_text_stats.get('skipped', 0)}\n"
                    "- PDF paths are recorded in `extra_fields.full_text` under `papers/full_texts/`.\n"
                )
            else:
                content += "- Open-access PDFs are downloaded automatically when URLs are available.\n"

        print(content)
        return 0
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

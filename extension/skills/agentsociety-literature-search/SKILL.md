---
name: agentsociety-literature-search
description: Use when academic literature needs to be gathered or refreshed for a research topic, especially at the beginning of a project.
---

# Academic Literature Search

Search academic literature through the **academic literature search gateway** (MCP) and save results to the workspace `papers/` directory. Queries all configured data sources (local, arXiv, CrossRef, OpenAlex) by default.

The runtime connects via **MCP** using workspace `.env` only. You do **not** need Claude `mcp.json` for this skill.

## Plugin vs this skill

| Need | Where |
| ---- | ----- |
| Topic / keyword search across sources | **This skill** (`literature-search`) — requires MCP key |
| Open-access PDF helpers for search hits | **This skill** (`literature-full-text`) |
| Upload PDF/MD, paste DOI/arXiv, sync metadata, BibTeX import/export | **VS Code extension** literature library UI (public APIs + local files; **no MCP**) |

Do not reimplement DOI paste / local upload / Bib sync with this skill.

## When to Use

- User mentions "literature", "papers", "related work", "survey", or "background research"
- Starting a new research topic and `TOPIC.md` does not yet exist
- Existing `TOPIC.md` needs enrichment with more references
- User asks "what has been published on X?"
- User asks to refresh or expand `papers/literature_index.json` **via search**

**Do NOT use when:**

- User already has a well-defined hypothesis and wants to design experiments (use hypothesis skill)
- User needs to run a simulation (use experiment-config skill)
- User only wants to read a local PDF already in the workspace; open or summarize that file directly
- User wants to manage the local library (upload, DOI add, BibTeX, sync fill) — use the extension literature UI
## Quick Reference

Use the Python interpreter from `.env`. See `CLAUDE.md` for setup.
Run commands from the workspace root through `.agentsociety/bin/ags.py`.

| Action                  | Command                                                                                                                                |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Basic search            | `$PYTHON_PATH .agentsociety/bin/ags.py literature-search "query"`                                                                      |
| Year range              | `$PYTHON_PATH .agentsociety/bin/ags.py literature-search "query" --year-from 2020 --year-to 2024`                                      |
| Complex topic           | `$PYTHON_PATH .agentsociety/bin/ags.py literature-search "complex query" --multi-query`                                                |
| Custom workspace        | `$PYTHON_PATH .agentsociety/bin/ags.py literature-search "query" --workspace /path/to/dir`                                             |
| List PDF candidates     | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text candidates`                                                                |
| Download open PDF       | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text download --entry 1`                                                        |
| Register local PDF      | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text register --entry 1 --file /path/to/paper.pdf`                              |
| Mark no PDF found       | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text mark --entry 1 --status no_candidate --reason "No open PDF URL available"` |
| List entries needing notes | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text enrich --dry-run`                                                       |
| Mark note supplemented  | `$PYTHON_PATH .agentsociety/bin/ags.py literature-full-text enrich --entry 1`                                                          |

## Configuration (required)

Set in the workspace `.env`:

```bash
LITERATURE_SEARCH_MCP_URL=https://llmapi.fiblab.net/mcp/
LITERATURE_SEARCH_API_KEY=sk-your-litellm-virtual-key
```

Use an MCP gateway URL ending in `/mcp/` (trailing slash required on fiblab). The API key must be a LiteLLM virtual key (`sk-...`) with **academic literature search** permission on that gateway.

## Parameters

| Parameter     | Type    | Required | Description                          |
| ------------- | ------- | -------- | ------------------------------------ |
| query         | string  | Yes      | Search query (positional)            |
| --year-from   | integer | No       | Start year filter                    |
| --year-to     | integer | No       | End year filter                      |
| --workspace   | string  | No       | Workspace path (default: cwd)        |
| --multi-query | flag    | No       | Split complex queries into subtopics |

Full-text helper parameters:

| Command                           | Important Parameters                                          | Description                                                                   |
| --------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `literature-full-text candidates` | `--entry N` optional                                          | Show candidate URLs inferred from `literature_index.json`                     |
| `literature-full-text download`   | `--entry N`, `--url URL` optional                             | Try open PDF URLs and update `extra_fields.full_text`                         |
| `literature-full-text register`   | `--entry N`, `--file PATH`                                    | Copy/register a local PDF and update the index                                |
| `literature-full-text mark`       | `--entry N`, `--status no_candidate\|failed`, `--reason TEXT` | Record why a PDF is unavailable                                               |
| `literature-full-text enrich`     | `--entry N` or `--dry-run`                                    | List or mark entries whose Markdown notes were manually supplemented          |

## Recommended Workflow

1. Confirm `.env` has `LITERATURE_SEARCH_MCP_URL` and `LITERATURE_SEARCH_API_KEY`.
2. Read `TOPIC.md` if it exists. Use the research question, scope, target population, and key constructs to form the query.
3. Run one focused search with the default command (returns 10 papers). Only add `--limit` when the user explicitly asks for a different count.
4. Use `--year-from` / `--year-to` when the user wants recent work or a defined historical window.
5. Use `--multi-query` for topics with multiple constructs, methods, or domains.
6. Inspect `papers/literature_index.json` and `papers/full_texts/` after the command completes.
7. Summarize findings in research terms, not just as a list of titles.
8. For paywalled or failed PDFs, follow "Optional Full-Text Retrieval" below.

## Output

```
papers/
  literature_index.json    # Auto-created/updated catalog
  article_title.md         # Per-article markdown summaries
  full_texts/              # Open-access PDFs (auto-downloaded when available)
```

Each article contains: `title`, `authors`, `abstract`, `year`, `journal`, `doi`, `url`, `score`, `source`.

## Index Contract

`papers/literature_index.json` follows this shape:

```json
{
  "version": "1.0",
  "created_at": "...",
  "updated_at": "...",
  "entries": [
    {
      "title": "Article title",
      "journal": "Journal or venue",
      "doi": "10.xxxx/xxxx",
      "abstract": "...",
      "file_path": "papers/article_title.md",
      "file_type": "markdown",
      "source": "literature_search",
      "query": "original query",
      "avg_similarity": 0.84,
      "saved_at": "...",
      "extra_fields": {
        "authors": ["..."],
        "year": 2024,
        "url": "https://..."
      }
    }
  ]
}
```

Keep `file_path` pointed at the Markdown note. PDF paths belong in `extra_fields.full_text.file_path`.

## Optional Full-Text Retrieval

The search command automatically tries open-access PDF downloads. Publisher paywalls are not bypassed. See `references/full-text-retrieval.md` for manual follow-up. When a PDF is unavailable, mark the reason, optionally supplement the Markdown note from the abstract/user-provided material, then `literature-full-text enrich --entry N`.

## Common Mistakes

| Mistake                                    | Fix                                                       |
| ------------------------------------------ | --------------------------------------------------------- |
| Missing trailing slash on fiblab MCP       | Use `https://llmapi.fiblab.net/mcp/`                      |
| Only configuring Claude `mcp.json`         | Add `LITERATURE_SEARCH_MCP_*` to workspace `.env`         |
| Key works for LLM but not literature       | Use **sk-** key with literature permission on the gateway |
| Non-MCP URL in `LITERATURE_SEARCH_MCP_URL` | Use gateway MCP URL `https://llmapi.fiblab.net/mcp/`      |

## References

- `references/data-sources.md` — data sources and response fields
- `references/full-text-retrieval.md` — PDF workflow

## Pipeline Position

**Predecessors:** None (entry point)
**Successors:** hypothesis
**Required Sub-Skills:** None

## Progress Tracking

After search completes successfully:

```bash
$PYTHON .agentsociety/bin/ags.py research-pipeline update-stage literature_search completed --metadata '{"paper_count": N}'
```

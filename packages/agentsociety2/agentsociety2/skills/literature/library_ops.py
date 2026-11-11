"""文献库同步、PDF 下载与 BibTeX 导入导出的扩展端辅助函数。

仅插件侧使用：公共元数据 API + 本地文件，**不**调用文献 MCP 网关
（主题检索仍走付费技能路径）。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentsociety2.skills.literature.doi_lookup import (
    BibliographicRecord,
    classify_identifier,
    extract_identifier_from_pdf,
    lookup_identifier,
)
from agentsociety2.skills.literature.formatter import (
    format_article_as_markdown,
    sanitize_filename,
)
from agentsociety2.skills.literature.full_text import (
    download_entry_pdf,
    entry_extra_fields,
    full_text_status,
    index_entries,
    load_literature_index_dict,
    save_literature_index_dict,
)
from agentsociety2.skills.literature.ingest import (
    IngestResult,
    append_entry,
    find_duplicate_index,
    load_or_create_index,
)
from agentsociety2.skills.literature.models import LiteratureEntry


@dataclass(frozen=True)
class SyncStats:
    """一次同步 / 下载过程的计数统计。"""

    metadata_updated: int = 0
    metadata_skipped: int = 0
    metadata_failed: int = 0
    pdf_downloaded: int = 0
    pdf_skipped: int = 0
    pdf_failed: int = 0
    pdf_no_candidate: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _extra(entry: dict[str, Any]) -> dict[str, Any]:
    return entry_extra_fields(entry)


def _authors_of(entry: dict[str, Any]) -> list[str]:
    extra = _extra(entry)
    raw = entry.get("authors") or extra.get("authors") or []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    return []


def _year_of(entry: dict[str, Any]) -> int | None:
    extra = _extra(entry)
    value = entry.get("year") if entry.get("year") is not None else extra.get("year")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _needs_metadata(entry: dict[str, Any]) -> bool:
    """核心书目字段不完整时返回 True。"""
    if not (entry.get("title") or "").strip():
        return True
    if not _authors_of(entry):
        return True
    if _year_of(entry) is None:
        return True
    if not (entry.get("abstract") or "").strip():
        return True
    return bool(not (entry.get("journal") or "").strip())


def _lookup_raw(entry: dict[str, Any]) -> str | None:
    """挑选适合传给 lookup_identifier 的 DOI / arXiv 标识符字符串。"""
    extra = _extra(entry)
    for key in ("doi",):
        value = entry.get(key) or extra.get(key)
        if isinstance(value, str) and value.strip():
            try:
                classify_identifier(value.strip())
                return value.strip()
            except ValueError:
                pass

    for key in ("identifier", "arxiv_id", "article_id", "url", "scanned_identifier"):
        value = entry.get(key) or extra.get(key)
        if isinstance(value, str) and value.strip():
            try:
                classify_identifier(value.strip())
                return value.strip()
            except ValueError:
                pass

    title = (entry.get("title") or "").strip()
    if title:
        try:
            classify_identifier(title)
            return title
        except ValueError:
            pass

    # Last resort: scan the attached local PDF for an embedded DOI / arXiv id.
    full_text = extra.get("full_text")
    if isinstance(full_text, dict):
        pdf_rel = full_text.get("file_path")
        if isinstance(pdf_rel, str) and pdf_rel.strip():
            # Caller resolves against workspace in enrich_metadata.
            return f"pdf:{pdf_rel.strip()}"
    return None


def _resolve_under_workspace(workspace: Path, relative: str) -> Path | None:
    """在 ``workspace`` 下解析 ``relative`` ；路径越界时返回 None。"""
    root = workspace.resolve()
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _resolve_lookup_raw(workspace: Path, raw: str) -> str | None:
    if raw.startswith("pdf:"):
        pdf_path = _resolve_under_workspace(workspace, raw[4:])
        if pdf_path is not None and pdf_path.is_file():
            return extract_identifier_from_pdf(pdf_path)
        return None
    return raw


def _apply_record(entry: dict[str, Any], record: BibliographicRecord) -> bool:
    """用 ``record`` 填充缺失的元数据字段；有任何字段被更新时返回 True。"""
    changed = False
    extra = _extra(entry)

    if record.title and (
        not (entry.get("title") or "").strip()
        or entry.get("title") == extra.get("original_name")
        or (entry.get("title") or "").endswith(".pdf")
    ):
        entry["title"] = record.title
        changed = True

    if record.venue and not (entry.get("journal") or "").strip():
        entry["journal"] = record.venue
        changed = True

    if record.doi and not (entry.get("doi") or "").strip():
        entry["doi"] = record.doi
        changed = True

    if record.abstract and not (entry.get("abstract") or "").strip():
        entry["abstract"] = record.abstract
        changed = True

    if record.authors and not _authors_of(entry):
        extra["authors"] = list(record.authors)
        changed = True

    if record.year is not None and _year_of(entry) is None:
        extra["year"] = record.year
        changed = True

    if record.url and not extra.get("url") and not entry.get("url"):
        extra["url"] = record.url
        changed = True

    if record.cite_key and not extra.get("cite_key"):
        extra["cite_key"] = record.cite_key
        changed = True

    extra["identifier"] = record.identifier
    extra["id_type"] = record.id_type
    extra["metadata_synced_at"] = _now_iso()
    return changed


def _select_entries(
    data: dict[str, Any], entry_ids: list[int] | None
) -> list[tuple[int, dict[str, Any]]]:
    entries = index_entries(data)
    if entry_ids is None:
        return [(i, e) for i, e in enumerate(entries) if isinstance(e, dict)]
    selected: list[tuple[int, dict[str, Any]]] = []
    for idx in entry_ids:
        if idx < 0 or idx >= len(entries):
            raise IndexError(f"Entry id {idx} out of range (0..{len(entries) - 1})")
        entry = entries[idx]
        if not isinstance(entry, dict):
            raise TypeError(f"Entry {idx} is not an object")
        selected.append((idx, entry))
    return selected


def enrich_metadata(
    workspace: Path,
    *,
    entry_ids: list[int] | None = None,
    timeout: float = 20.0,
) -> SyncStats:
    """在已知标识符时，通过 DOI / arXiv 公共查询补全缺失元数据。"""
    workspace = workspace.resolve()
    index_path, data = load_literature_index_dict(workspace)
    updated = skipped = failed = 0

    for _, entry in _select_entries(data, entry_ids):
        if not _needs_metadata(entry):
            skipped += 1
            continue
        raw = _lookup_raw(entry)
        if not raw:
            skipped += 1
            continue
        resolved = _resolve_lookup_raw(workspace, raw)
        if not resolved:
            skipped += 1
            continue
        try:
            record = lookup_identifier(resolved, timeout=timeout)
        except (ValueError, OSError):
            failed += 1
            continue
        if _apply_record(entry, record):
            updated += 1
        else:
            skipped += 1

    save_literature_index_dict(index_path, data)
    return SyncStats(
        metadata_updated=updated,
        metadata_skipped=skipped,
        metadata_failed=failed,
    )


def download_missing_pdfs(
    workspace: Path,
    *,
    entry_ids: list[int] | None = None,
    force: bool = False,
) -> SyncStats:
    """为仍缺少本地 PDF 的条目尝试下载开放获取的 PDF。"""
    workspace = workspace.resolve()
    index_path, data = load_literature_index_dict(workspace)
    downloaded = skipped = failed = no_candidate = 0

    for _, entry in _select_entries(data, entry_ids):
        if not force and full_text_status(entry) == "downloaded":
            skipped += 1
            continue
        outcome = download_entry_pdf(
            workspace,
            entry,
            skip_if_downloaded=not force,
        )
        if outcome == "downloaded":
            downloaded += 1
        elif outcome == "skipped":
            skipped += 1
        elif outcome == "no_candidate":
            no_candidate += 1
        else:
            failed += 1

    save_literature_index_dict(index_path, data)
    return SyncStats(
        pdf_downloaded=downloaded,
        pdf_skipped=skipped,
        pdf_failed=failed,
        pdf_no_candidate=no_candidate,
    )


def sync_library(
    workspace: Path,
    *,
    entry_ids: list[int] | None = None,
    timeout: float = 20.0,
    download_pdfs: bool = True,
) -> SyncStats:
    """先补全不完整的元数据，再为缺口尝试下载 OA PDF。"""
    meta = enrich_metadata(workspace, entry_ids=entry_ids, timeout=timeout)
    if not download_pdfs:
        return meta
    pdf = download_missing_pdfs(workspace, entry_ids=entry_ids, force=False)
    return SyncStats(
        metadata_updated=meta.metadata_updated,
        metadata_skipped=meta.metadata_skipped,
        metadata_failed=meta.metadata_failed,
        pdf_downloaded=pdf.pdf_downloaded,
        pdf_skipped=pdf.pdf_skipped,
        pdf_failed=pdf.pdf_failed,
        pdf_no_candidate=pdf.pdf_no_candidate,
    )


def _cite_key_for_entry(entry: dict[str, Any], fallback: str) -> str:
    extra = _extra(entry)
    existing = extra.get("cite_key")
    if isinstance(existing, str) and existing.strip():
        return re.sub(r"[^A-Za-z0-9_]", "", existing.strip())[:64] or fallback
    authors = _authors_of(entry)
    year = _year_of(entry)
    title = (entry.get("title") or "item").split()[0]
    last = authors[0].split()[-1] if authors else "anon"
    last = re.sub(r"[^A-Za-z0-9]", "", last).lower() or "anon"
    year_part = str(year) if year else "nd"
    title_token = re.sub(r"[^A-Za-z0-9]+", "", title)[:12].lower() or "item"
    return f"{last}{year_part}{title_token}"[:64]


def entry_to_bibtex(entry: dict[str, Any], *, index: int = 0) -> str:
    """将一个文献索引条目渲染为 BibTeX ``@article`` / ``@misc`` 块。"""
    extra = _extra(entry)
    title = (entry.get("title") or "Untitled").strip()
    authors = _authors_of(entry)
    year = _year_of(entry)
    venue = (entry.get("journal") or "").strip() or None
    doi = (entry.get("doi") or "").strip() or None
    url = (
        (entry.get("url") if isinstance(entry.get("url"), str) else None)
        or (extra.get("url") if isinstance(extra.get("url"), str) else None)
        or (f"https://doi.org/{doi}" if doi else None)
    )
    cite_key = _cite_key_for_entry(entry, f"entry{index}")
    entry_type = "article" if doi and venue else "misc"
    author_str = " and ".join(authors) if authors else "Unknown"

    def esc(value: str) -> str:
        return value.replace("{", "\\{").replace("}", "\\}")

    lines = [f"@{entry_type}{{{cite_key},"]
    lines.append(f"  title = {{{esc(title)}}},")
    lines.append(f"  author = {{{esc(author_str)}}},")
    if year is not None:
        lines.append(f"  year = {{{year}}},")
    if venue:
        field = "journal" if entry_type == "article" else "howpublished"
        lines.append(f"  {field} = {{{esc(venue)}}},")
    if doi:
        lines.append(f"  doi = {{{esc(doi)}}},")
    if url:
        lines.append(f"  url = {{{esc(url)}}},")
    lines.append("}")
    return "\n".join(lines)


def export_bibtex(
    workspace: Path,
    *,
    entry_ids: list[int] | None = None,
    write_library_bib: bool = True,
) -> dict[str, Any]:
    """将选中（或全部）条目导出为 BibTeX 文本；可选写入 ``papers/library.bib`` 。"""
    workspace = workspace.resolve()
    _, data = load_literature_index_dict(workspace)
    blocks: list[str] = []
    for idx, entry in _select_entries(data, entry_ids):
        blocks.append(entry_to_bibtex(entry, index=idx))
    text = "\n\n".join(blocks) + ("\n" if blocks else "")
    out_path: str | None = None
    if write_library_bib:
        bib_path = workspace / "papers" / "library.bib"
        bib_path.parent.mkdir(parents=True, exist_ok=True)
        bib_path.write_text(text, encoding="utf-8")
        out_path = "papers/library.bib"
    return {"bibtex": text, "count": len(blocks), "path": out_path}


_BIB_ENTRY_RE = re.compile(
    r"@(?P<type>\w+)\s*\{\s*(?P<key>[^,]+)\s*,(?P<body>.*?)\n\s*\}",
    re.IGNORECASE | re.DOTALL,
)
_BIB_FIELD_RE = re.compile(
    r"(?P<name>\w+)\s*=\s*(?:\{(?P<braced>.*?)\}|\"(?P<quoted>.*?)\"|(?P<bare>[^,]+))\s*,?",
    re.IGNORECASE | re.DOTALL,
)


def _parse_bibtex(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for match in _BIB_ENTRY_RE.finditer(text):
        fields: dict[str, str] = {
            "_type": match.group("type").lower(),
            "_key": match.group("key").strip(),
        }
        for field in _BIB_FIELD_RE.finditer(match.group("body")):
            name = field.group("name").lower()
            value = (
                field.group("braced")
                or field.group("quoted")
                or field.group("bare")
                or ""
            )
            fields[name] = value.strip().rstrip(",")
        records.append(fields)
    return records


def import_bibtex(workspace: Path, bib_path: Path) -> dict[str, Any]:
    """将 ``.bib`` 文件导入文献索引（生成新的 Markdown 笔记）。"""
    workspace = workspace.resolve()
    src = bib_path if bib_path.is_absolute() else (workspace / bib_path)
    src = src.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"BibTeX file not found: {src}")

    records = _parse_bibtex(src.read_text(encoding="utf-8"))
    index_path, index = load_or_create_index(workspace)
    added = 0
    duplicates = 0
    papers_dir = workspace / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    for rec in records:
        title = rec.get("title") or rec.get("_key") or "Untitled"
        title = re.sub(r"\s+", " ", title).strip()
        doi = rec.get("doi")
        authors_raw = rec.get("author") or ""
        authors = [a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()]
        year = None
        if rec.get("year") and rec["year"].isdigit():
            year = int(rec["year"])
        venue = rec.get("journal") or rec.get("booktitle") or rec.get("howpublished")
        url = rec.get("url")
        if doi and not url:
            url = f"https://doi.org/{doi}"

        dup = find_duplicate_index(index, title=title, doi=doi)
        if dup is not None:
            duplicates += 1
            continue

        article = {
            "title": title,
            "journal": venue,
            "doi": doi,
            "abstract": rec.get("abstract"),
            "year": year,
            "url": url,
            "authors": authors,
            "source": "bibtex_import",
            "source_name": "bibtex",
        }
        stamp = datetime.now(UTC).isoformat().replace(":", "-").replace(".", "-")[:19]
        note_name = f"{sanitize_filename(title)}_{stamp}.md"
        note_path = papers_dir / note_name
        note_path.write_text(
            format_article_as_markdown(article, "bibtex_import"),
            encoding="utf-8",
        )
        entry = LiteratureEntry(
            title=title,
            journal=venue,
            doi=doi,
            abstract=rec.get("abstract"),
            file_path=note_path.relative_to(workspace).as_posix(),
            file_type="markdown",
            source="user_upload",
            query="bibtex_import",
            saved_at=_now_iso(),
            extra_fields={
                "authors": authors,
                "year": year,
                "url": url,
                "cite_key": rec.get("_key"),
                "ingest": "bibtex_import",
            },
        )
        result: IngestResult = append_entry(index_path, index, entry)
        # reload index after append (entries mutated on same object)
        if result.added:
            added += 1
        elif result.duplicate:
            duplicates += 1

    return {"added": added, "duplicates": duplicates, "parsed": len(records)}


def _parse_entry_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(part.strip()) for part in raw.split(",") if part.strip() != ""]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extension literature library ops (sync metadata/PDF, BibTeX). "
            "Not a Claude skill tool."
        )
    )
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Fill missing metadata and try OA PDF download")
    sync.add_argument("--entries", help="Comma-separated 0-based entry ids")
    sync.add_argument("--timeout", type=float, default=20.0)
    sync.add_argument("--no-pdf", action="store_true", help="Only enrich metadata")

    dl = sub.add_parser("download-pdf", help="Download OA PDF for entries")
    dl.add_argument("--entries", help="Comma-separated 0-based entry ids")
    dl.add_argument("--force", action="store_true")

    export_bib = sub.add_parser("export-bib", help="Export BibTeX / write library.bib")
    export_bib.add_argument("--entries", help="Comma-separated 0-based entry ids")
    export_bib.add_argument(
        "--stdout-only",
        action="store_true",
        help="Do not write papers/library.bib",
    )

    import_bib = sub.add_parser("import-bib", help="Import a .bib file into the index")
    import_bib.add_argument("file", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()

    try:
        if args.command == "sync":
            stats = sync_library(
                workspace,
                entry_ids=_parse_entry_ids(args.entries),
                timeout=args.timeout,
                download_pdfs=not args.no_pdf,
            )
            payload: dict[str, Any] = {"ok": True, **stats.to_dict()}
        elif args.command == "download-pdf":
            stats = download_missing_pdfs(
                workspace,
                entry_ids=_parse_entry_ids(args.entries),
                force=args.force,
            )
            payload = {"ok": True, **stats.to_dict()}
        elif args.command == "export-bib":
            result = export_bibtex(
                workspace,
                entry_ids=_parse_entry_ids(args.entries),
                write_library_bib=not args.stdout_only,
            )
            payload = {"ok": True, **result}
        else:
            result = import_bibtex(workspace, args.file)
            payload = {"ok": True, **result}
    except (ValueError, FileNotFoundError, OSError, IndexError, TypeError) as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=__import__("sys").stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

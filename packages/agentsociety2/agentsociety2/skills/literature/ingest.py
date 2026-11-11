"""从 DOI/arXiv 或本地文件添加文献条目的共享辅助函数。

供 VS Code 扩展 UI（上传 / 粘贴 DOI）使用，不属于 Claude 文献检索技能的
对外接口——主题检索与 OA 全文仍走 ``search`` / ``full_text`` / MCP。
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agentsociety2.skills.literature.doi_lookup import (
    BibliographicRecord,
    extract_identifier_from_pdf,
    lookup_identifier,
)
from agentsociety2.skills.literature.formatter import (
    format_article_as_markdown,
    sanitize_filename,
)
from agentsociety2.skills.literature.models import LiteratureEntry, LiteratureIndex

FileType = Literal["markdown", "pdf", "docx", "txt", "md"]


@dataclass(frozen=True)
class IngestResult:
    """单次入库操作的结果。"""

    added: bool
    duplicate: bool
    title: str
    file_path: str
    doi: str | None
    message: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_or_create_index(workspace: Path) -> tuple[Path, LiteratureIndex]:
    """加载 ``papers/literature_index.json`` ，缺失时创建空索引。"""
    papers_dir = workspace / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    index_path = papers_dir / "literature_index.json"
    if not index_path.exists():
        now = _now_iso()
        index = LiteratureIndex(entries=[], created_at=now, updated_at=now)
        index_path.write_text(
            json.dumps(index.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return index_path, index

    data = json.loads(index_path.read_text(encoding="utf-8"))
    return index_path, LiteratureIndex(**data)


def save_index(index_path: Path, index: LiteratureIndex) -> None:
    """持久化文献索引并刷新更新时间。"""
    index.updated_at = _now_iso()
    index_path.write_text(
        json.dumps(index.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_duplicate_index(
    index: LiteratureIndex,
    *,
    title: str | None,
    doi: str | None,
) -> int | None:
    """按 DOI 或标题查找重复条目的下标，找不到时返回 ``None`` 。"""
    doi_key = doi.strip().lower() if doi else ""
    title_key = title.strip().lower() if title else ""
    for idx, entry in enumerate(index.entries):
        if doi_key and entry.doi and entry.doi.strip().lower() == doi_key:
            return idx
        if title_key and entry.title and entry.title.strip().lower() == title_key:
            return idx
    return None


def _file_type_for(path: Path) -> FileType:
    ext = path.suffix.lower()
    if ext in {".md", ".markdown"}:
        return "markdown"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext == ".txt":
        return "txt"
    raise ValueError(f"Unsupported literature file type: {path.suffix}")


def _unique_dest(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for n in range(2, 1000):
        alt = directory / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
    raise ValueError(f"Could not find a free filename for {filename}")


def append_entry(
    index_path: Path,
    index: LiteratureIndex,
    entry: LiteratureEntry,
) -> IngestResult:
    dup = find_duplicate_index(index, title=entry.title, doi=entry.doi)
    if dup is not None:
        existing = index.entries[dup]
        return IngestResult(
            added=False,
            duplicate=True,
            title=existing.title,
            file_path=existing.file_path,
            doi=existing.doi,
            message=f"Already in library: {existing.title}",
        )
    index.entries.append(entry)
    save_index(index_path, index)
    return IngestResult(
        added=True,
        duplicate=False,
        title=entry.title,
        file_path=entry.file_path,
        doi=entry.doi,
        message=f"Added: {entry.title}",
    )


def _record_to_article(record: BibliographicRecord) -> dict[str, Any]:
    return {
        "title": record.title,
        "journal": record.venue,
        "doi": record.doi,
        "abstract": record.abstract,
        "year": record.year,
        "url": record.url,
        "authors": list(record.authors),
        "source": record.id_type,
        "source_name": "doi_lookup",
        "cite_key": record.cite_key,
        "identifier": record.identifier,
    }


def _write_note(workspace: Path, article: dict[str, Any], query: str) -> Path:
    papers_dir = workspace / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat().replace(":", "-").replace(".", "-")[:19]
    filename = (
        f"{sanitize_filename(str(article.get('title') or 'Untitled'))}_{stamp}.md"
    )
    note_path = _unique_dest(papers_dir, filename)
    note_path.write_text(format_article_as_markdown(article, query), encoding="utf-8")
    return note_path


def add_from_identifier(
    workspace: Path,
    raw_identifier: str,
    *,
    timeout: float = 20.0,
) -> IngestResult:
    """查询 DOI 或 arXiv 编号，并添加 Markdown 笔记与索引条目。"""
    workspace = workspace.resolve()
    record = lookup_identifier(raw_identifier, timeout=timeout)
    index_path, index = load_or_create_index(workspace)

    dup = find_duplicate_index(index, title=record.title, doi=record.doi)
    if dup is not None:
        existing = index.entries[dup]
        return IngestResult(
            added=False,
            duplicate=True,
            title=existing.title,
            file_path=existing.file_path,
            doi=existing.doi,
            message=f"Already in library: {existing.title}",
        )

    article = _record_to_article(record)
    query = f"{record.id_type}:{record.identifier}"
    note_path = _write_note(workspace, article, query)

    extra: dict[str, Any] = {
        "authors": list(record.authors),
        "year": record.year,
        "url": record.url,
        "cite_key": record.cite_key,
        "identifier": record.identifier,
        "id_type": record.id_type,
        "ingest": "doi_lookup",
    }
    entry = LiteratureEntry(
        title=record.title,
        journal=record.venue,
        doi=record.doi,
        abstract=record.abstract,
        file_path=note_path.relative_to(workspace).as_posix(),
        file_type="markdown",
        source="user_upload",
        query=query,
        saved_at=_now_iso(),
        extra_fields=extra,
    )
    return append_entry(index_path, index, entry)


def add_from_local_file(
    workspace: Path,
    file_path: Path,
    *,
    title: str | None = None,
) -> IngestResult:
    """将本地 Markdown 笔记或 PDF 添加到文献索引。

    Markdown/txt 直接存放在 ``papers/`` 下作为条目的 ``file_path`` 。
    PDF 遵循与全文辅助工具相同的约定：条目的 ``file_path`` 是一份占位
    Markdown 笔记，PDF 本体复制到 ``papers/full_texts/`` 并记录在
    ``extra_fields.full_text`` 下。

    此操作会创建**新**条目；要为已有条目挂接 PDF，请改用
    ``literature-full-text register`` 。
    """
    workspace = workspace.resolve()
    src = file_path if file_path.is_absolute() else (workspace / file_path)
    src = src.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")

    file_type = _file_type_for(src)
    papers_dir = workspace / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    entry_title = (title or src.stem).strip() or src.stem
    index_path, index = load_or_create_index(workspace)

    if file_type == "pdf":
        full_text_dir = papers_dir / "full_texts"
        full_text_dir.mkdir(parents=True, exist_ok=True)

        try:
            src.relative_to(full_text_dir.resolve())
            already_in_full_texts = True
        except ValueError:
            already_in_full_texts = False

        if already_in_full_texts:
            pdf_dest = src
        else:
            pdf_dest = _unique_dest(
                full_text_dir, f"{sanitize_filename(entry_title)}.pdf"
            )
            shutil.copy2(src, pdf_dest)
            # DnD first drops into papers/; remove that loose copy after relocating.
            try:
                loose_rel = src.relative_to(papers_dir.resolve())
                if loose_rel.parts and loose_rel.parts[0] != "full_texts":
                    src.unlink(missing_ok=True)
            except ValueError:
                # The source can be outside ``papers_dir`` (for example an
                # uploaded temporary file), in which case no loose copy exists.
                pass

        pdf_rel = pdf_dest.relative_to(workspace).as_posix()

        article: dict[str, Any] = {
            "title": entry_title,
            "source": "user_upload",
            "source_name": "local_pdf",
        }
        extra: dict[str, Any] = {
            "ingest": "local_file",
            "original_name": src.name,
            "full_text": {
                "file_path": pdf_rel,
                "status": "downloaded",
                "source": "user_upload",
                "updated_at": _now_iso(),
            },
        }
        doi: str | None = None
        abstract: str | None = None
        journal: str | None = None

        # Best-effort: scan PDF for DOI/arXiv and fill metadata from public APIs.
        scanned = extract_identifier_from_pdf(pdf_dest)
        if scanned:
            try:
                record = lookup_identifier(scanned)
                entry_title = record.title or entry_title
                doi = record.doi
                abstract = record.abstract
                journal = record.venue
                article = {
                    "title": entry_title,
                    "journal": journal,
                    "doi": doi,
                    "abstract": abstract,
                    "year": record.year,
                    "url": record.url,
                    "authors": list(record.authors),
                    "source": "user_upload",
                    "source_name": "local_pdf",
                }
                extra.update(
                    {
                        "authors": list(record.authors),
                        "year": record.year,
                        "url": record.url,
                        "cite_key": record.cite_key,
                        "identifier": record.identifier,
                        "id_type": record.id_type,
                        "ingest": "local_file+doi_lookup",
                    }
                )
                dup = find_duplicate_index(index, title=entry_title, doi=doi)
                if dup is not None:
                    if not already_in_full_texts:
                        pdf_dest.unlink(missing_ok=True)
                    existing = index.entries[dup]
                    return IngestResult(
                        added=False,
                        duplicate=True,
                        title=existing.title,
                        file_path=existing.file_path,
                        doi=existing.doi,
                        message=f"Already in library: {existing.title}",
                    )
            except (ValueError, OSError):
                extra["scanned_identifier"] = scanned

        note_path = _write_note(workspace, article, "user_upload")
        entry = LiteratureEntry(
            title=entry_title,
            journal=journal,
            doi=doi,
            abstract=abstract,
            file_path=note_path.relative_to(workspace).as_posix(),
            file_type="markdown",
            source="user_upload",
            query=None,
            saved_at=_now_iso(),
            extra_fields=extra,
        )
        return append_entry(index_path, index, entry)

    try:
        rel = src.relative_to(workspace)
        under_papers = rel.parts and rel.parts[0] == "papers"
    except ValueError:
        under_papers = False

    if under_papers and rel is not None:
        note_rel = rel.as_posix()
    else:
        dest = _unique_dest(papers_dir, src.name)
        shutil.copy2(src, dest)
        note_rel = dest.relative_to(workspace).as_posix()

    entry = LiteratureEntry(
        title=entry_title,
        journal=None,
        doi=None,
        abstract=None,
        file_path=note_rel,
        file_type="markdown" if file_type in {"markdown", "md", "txt"} else file_type,
        source="user_upload",
        query=None,
        saved_at=_now_iso(),
        extra_fields={"ingest": "local_file", "original_name": src.name},
    )
    return append_entry(index_path, index, entry)


def _result_to_dict(result: IngestResult) -> dict[str, Any]:
    return {
        "added": result.added,
        "duplicate": result.duplicate,
        "title": result.title,
        "file_path": result.file_path,
        "doi": result.doi,
        "message": result.message,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extension helper: add literature by DOI/arXiv or local file. "
            "Not a Claude skill tool — use literature-search / literature-full-text for agents."
        )
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Workspace root (default: cwd)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a single JSON object on success",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_id = sub.add_parser("add-id", help="Look up DOI or arXiv id and add")
    add_id.add_argument("identifier", help="DOI, doi.org URL, or arXiv id/URL")
    add_id.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout seconds (default: 20)",
    )

    add_file = sub.add_parser("add-file", help="Register a local PDF or Markdown file")
    add_file.add_argument("file", type=Path, help="Path to PDF/MD file")
    add_file.add_argument("--title", help="Override entry title")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()

    try:
        if args.command == "add-id":
            result = add_from_identifier(
                workspace, args.identifier, timeout=args.timeout
            )
        else:
            result = add_from_local_file(workspace, args.file, title=args.title)
    except (ValueError, FileNotFoundError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=__import__("sys").stderr)
        return 1

    payload = {"ok": True, **_result_to_dict(result)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(result.message)
        print(f"file_path={result.file_path}")
    return 0 if result.added or result.duplicate else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""通过公共元数据 API 查询 DOI / arXiv 标识符。

供扩展端“粘贴 DOI”入库流程共用的库，独立于文献 MCP 主题检索路径
（``core`` / ``mcp_client`` ）。
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_DOI_URL_RE = re.compile(
    r"(?i)^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)$"
)
_ARXIV_RE = re.compile(
    r"(?i)^(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)?"
    r"(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$"
)
_CROSSREF_UA = "AgentSociety2-DOILookup/0.1 (mailto:agentsociety@fiblab.net)"

# Best-effort scan of PDF bytes for embedded DOI / arXiv ids (no PDF parser dep).
_PDF_DOI_RE = re.compile(rb"(?i)(?:doi[:\s]*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)")
_PDF_ARXIV_RE = re.compile(
    rb"(?i)(?:arxiv\.org/(?:abs|pdf)/|arxiv[:\s]+)(\d{4}\.\d{4,5})(?:v\d+)?"
)


def extract_identifier_from_pdf(
    path: Path,
    *,
    max_bytes: int = 512_000,
) -> str | None:
    """扫描 PDF 开头以明文字节形式内嵌的 DOI 或 arXiv 编号。

    学术 PDF 中这类字符串通常未经压缩。返回第一个可信的标识符；
    未找到时返回 ``None`` 。无需依赖 PDF 解析库。
    """
    data = Path(path).read_bytes()[:max_bytes]
    for match in _PDF_DOI_RE.finditer(data):
        raw = match.group(1).decode("ascii", errors="ignore").rstrip(".,;)")
        try:
            return normalize_doi(raw)
        except ValueError:
            continue
    for match in _PDF_ARXIV_RE.finditer(data):
        raw = match.group(1).decode("ascii", errors="ignore")
        try:
            return normalize_arxiv_id(raw)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class BibliographicRecord:
    """公共元数据查询返回的规范化书目字段。"""

    identifier: str
    id_type: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    doi: str | None
    url: str | None
    abstract: str | None
    cite_key: str


def normalize_doi(raw: str) -> str:
    """去除 URL/doi: 前缀，返回裸 DOI 字符串。"""
    text = raw.strip()
    match = _DOI_URL_RE.match(text)
    if not match:
        raise ValueError(f"Not a DOI: {raw!r}")
    return match.group(1)


def normalize_arxiv_id(raw: str) -> str:
    """去除 arXiv URL/前缀，返回 ``YYYY.NNNNN`` （不含版本号）。"""
    text = raw.strip()
    match = _ARXIV_RE.match(text)
    if not match:
        raise ValueError(f"Not an arXiv id: {raw!r}")
    return match.group(1)


def classify_identifier(raw: str) -> tuple[str, str]:
    """识别标识符类型，返回 ``(id_type, normalized_id)`` ，类型为 ``doi`` 或 ``arxiv`` 。"""
    text = raw.strip()
    if not text:
        raise ValueError("Empty identifier")
    doi_match = _DOI_URL_RE.match(text)
    if doi_match:
        return "doi", doi_match.group(1)
    arxiv_match = _ARXIV_RE.match(text)
    if arxiv_match:
        return "arxiv", arxiv_match.group(1)
    raise ValueError(f"Unsupported identifier: {raw!r}")


def _http_get_json(url: str, *, accept: str, timeout: float = 20.0) -> Any:
    req = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": _CROSSREF_UA,
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url: str, *, accept: str, timeout: float = 20.0) -> str:
    req = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": _CROSSREF_UA,
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _author_name(author: dict[str, Any]) -> str:
    family = (author.get("family") or "").strip()
    given = (author.get("given") or "").strip()
    if family and given:
        return f"{given} {family}"
    if family:
        return family
    name = (author.get("name") or "").strip()
    if name:
        return name
    return "Unknown"


def _cite_key(
    authors: tuple[str, ...], year: int | None, title: str, fallback: str
) -> str:
    last = "anon"
    if authors:
        last = authors[0].split()[-1]
    last = re.sub(r"[^A-Za-z0-9]", "", last).lower() or "anon"
    year_part = str(year) if year else "nd"
    title_token = re.sub(r"[^A-Za-z0-9]+", "", title.split()[0] if title else "")[
        :12
    ].lower()
    title_token = title_token or "item"
    return f"{last}{year_part}{title_token}"[:64] or fallback


def _year_from_crossref(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "created"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def lookup_doi_crossref(doi: str, *, timeout: float = 20.0) -> BibliographicRecord:
    """从 Crossref ``/works/{doi}`` 获取元数据（期刊 DOI；并非覆盖所有 DataCite DOI）。"""
    bare = normalize_doi(doi)
    url = f"https://api.crossref.org/works/{quote(bare, safe='/')}"
    try:
        payload = _http_get_json(url, accept="application/json", timeout=timeout)
    except HTTPError as exc:
        raise ValueError(f"Crossref lookup failed for {bare}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Crossref lookup failed for {bare}: {exc}") from exc
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"Unexpected Crossref payload for {bare}")

    titles = message.get("title") or []
    title = titles[0].strip() if titles and isinstance(titles[0], str) else ""
    if not title:
        raise ValueError(f"Crossref entry has no title: {bare}")

    authors = tuple(
        _author_name(a) for a in (message.get("author") or []) if isinstance(a, dict)
    )
    year = _year_from_crossref(message)
    container = message.get("container-title") or []
    venue = container[0] if container and isinstance(container[0], str) else None
    abstract = message.get("abstract")
    if isinstance(abstract, str):
        abstract = re.sub(r"<[^>]+>", "", abstract).strip() or None
    else:
        abstract = None

    return BibliographicRecord(
        identifier=bare,
        id_type="doi",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=bare,
        url=f"https://doi.org/{bare}",
        abstract=abstract,
        cite_key=_cite_key(authors, year, title, bare.replace("/", "")),
    )


def lookup_doi_content_negotiation(
    doi: str, *, timeout: float = 20.0
) -> BibliographicRecord:
    """通过 DOI 内容协商（``doi.org`` ）获取 CSL-JSON。"""
    bare = normalize_doi(doi)
    url = f"https://doi.org/{quote(bare, safe='/')}"
    try:
        csl = _http_get_json(
            url,
            accept="application/vnd.citationstyles.csl+json",
            timeout=timeout,
        )
    except HTTPError as exc:
        raise ValueError(
            f"DOI content negotiation failed for {bare}: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise ValueError(f"DOI content negotiation failed for {bare}: {exc}") from exc

    if not isinstance(csl, dict):
        raise ValueError(f"Unexpected CSL payload for {bare}")

    title = (csl.get("title") or "").strip()
    if not title:
        raise ValueError(f"CSL entry has no title: {bare}")

    authors_list: list[str] = []
    for author in csl.get("author") or []:
        if not isinstance(author, dict):
            continue
        authors_list.append(_author_name(author))
    authors = tuple(authors_list)

    year = None
    issued = csl.get("issued") or {}
    parts = issued.get("date-parts") or []
    if parts and parts[0] and isinstance(parts[0][0], int):
        year = parts[0][0]

    venue = csl.get("container-title")
    if isinstance(venue, list):
        venue = venue[0] if venue else None
    if not isinstance(venue, str):
        venue = None

    return BibliographicRecord(
        identifier=bare,
        id_type="doi",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=bare,
        url=f"https://doi.org/{bare}",
        abstract=(csl.get("abstract") or None)
        if isinstance(csl.get("abstract"), str)
        else None,
        cite_key=_cite_key(authors, year, title, bare.replace("/", "")),
    )


_ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def lookup_arxiv(arxiv_id: str, *, timeout: float = 20.0) -> BibliographicRecord:
    """从 arXiv Atom API 获取元数据。"""
    bare = normalize_arxiv_id(arxiv_id)
    url = f"https://export.arxiv.org/api/query?id_list={quote(bare)}"
    xml_text = _http_get_text(url, accept="application/atom+xml", timeout=timeout)
    root = ET.fromstring(xml_text)
    entry = root.find("atom:entry", _ARXIV_NS)
    if entry is None:
        raise ValueError(f"arXiv returned no entry for {bare}")

    title = (
        entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or ""
    ).strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        raise ValueError(f"arXiv entry has no title: {bare}")

    authors = tuple(
        (node.findtext("atom:name", default="", namespaces=_ARXIV_NS) or "").strip()
        for node in entry.findall("atom:author", _ARXIV_NS)
    )
    authors = tuple(a for a in authors if a)

    published = entry.findtext("atom:published", default="", namespaces=_ARXIV_NS) or ""
    year = (
        int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
    )
    abstract = (
        entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or ""
    ).strip()
    abstract = re.sub(r"\s+", " ", abstract) or None

    doi_node = entry.find("arxiv:doi", _ARXIV_NS)
    doi = doi_node.text.strip() if doi_node is not None and doi_node.text else None

    return BibliographicRecord(
        identifier=bare,
        id_type="arxiv",
        title=title,
        authors=authors,
        year=year,
        venue="arXiv",
        doi=doi,
        url=f"https://arxiv.org/abs/{bare}",
        abstract=abstract,
        cite_key=_cite_key(authors, year, title, bare.replace(".", "")),
    )


def lookup_doi(doi: str, *, timeout: float = 20.0) -> BibliographicRecord:
    """通过内容协商获取 DOI 元数据（Crossref、DataCite 等）。"""
    return lookup_doi_content_negotiation(doi, timeout=timeout)


def lookup_identifier(raw: str, *, timeout: float = 20.0) -> BibliographicRecord:
    """对 ``raw`` 进行分类，并通过 DOI 内容协商或 arXiv 完成查询。"""
    id_type, normalized = classify_identifier(raw)
    if id_type == "doi":
        return lookup_doi(normalized, timeout=timeout)
    return lookup_arxiv(normalized, timeout=timeout)


def record_to_bibtex(record: BibliographicRecord) -> str:
    """渲染一个最小化的 BibTeX ``@article`` / ``@misc`` 条目。"""
    entry_type = "article" if record.id_type == "doi" and record.venue else "misc"
    authors = " and ".join(record.authors) if record.authors else "Unknown"

    def esc(value: str) -> str:
        return value.replace("{", "\\{").replace("}", "\\}")

    lines = [f"@{entry_type}{{{record.cite_key},"]
    lines.append(f"  title = {{{esc(record.title)}}},")
    lines.append(f"  author = {{{esc(authors)}}},")
    if record.year is not None:
        lines.append(f"  year = {{{record.year}}},")
    if record.venue:
        field = "journal" if entry_type == "article" else "howpublished"
        lines.append(f"  {field} = {{{esc(record.venue)}}},")
    if record.doi:
        lines.append(f"  doi = {{{esc(record.doi)}}},")
    if record.url:
        lines.append(f"  url = {{{esc(record.url)}}},")
    lines.append("}")
    return "\n".join(lines)

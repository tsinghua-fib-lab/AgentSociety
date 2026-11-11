"""Check English translation coverage and the rendered documentation language."""

from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from pathlib import Path

HAN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003134f]")
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class EnglishPage(HTMLParser):
    """Inspect visible text, including code examples and accessible labels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.issues: list[str] = []
        self.has_article = False

    def check(self, text: str, context: str) -> None:
        if HAN.search(text):
            snippet = " ".join(text.split())[:160]
            self.issues.append(f"line {self.getpos()[0]} ({context}): {snippet}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self.has_article = True
        for name, value in attrs:
            if name in {"alt", "title", "aria-label"} and value:
                self.check(value, name)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            position = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[position:]

    def handle_data(self, data: str) -> None:
        if not {"script", "style"}.intersection(self.stack):
            self.check(data, "text")


def check_english_html(root: Path) -> tuple[list[str], int]:
    """Check documentation pages, excluding the intentionally original source viewer."""
    errors: list[str] = []
    pages = 0
    english = root / "en"
    if not english.is_dir():
        return [f"English HTML directory not found: {english}"], 0
    for path in sorted(english.rglob("*.html")):
        if "_modules" in path.relative_to(english).parts:
            continue
        parser = EnglishPage()
        parser.feed(path.read_text(encoding="utf-8"))
        if parser.has_article:
            pages += 1
            errors.extend(
                f"{path.relative_to(root)}: {issue}" for issue in parser.issues
            )
    if not pages:
        errors.append(f"No documentation articles found in {english}")
    return errors, pages


def check_catalogs(templates: Path, locale: Path) -> tuple[list[str], int]:
    """Require an explicit non-fuzzy translation for every extracted message."""
    from babel.messages.pofile import read_po

    errors: list[str] = []
    messages = 0
    paths = sorted(templates.glob("*.pot"))
    if not paths:
        return [f"No gettext templates found in {templates}"], 0
    for template in paths:
        with template.open("rb") as stream:
            source = read_po(stream)
        catalog = locale / (template.stem + ".po")
        if not catalog.is_file():
            errors.append(f"Missing English catalog: {catalog}")
            continue
        with catalog.open("rb") as stream:
            target = read_po(stream, locale="en")
        expected = {item.id for item in source if item.id}
        for translation in target:
            if translation.id and translation.id not in expected:
                label = " ".join(str(translation.id).split())[:120]
                errors.append(f"{catalog.name}: unused active translation: {label}")
        for item in source:
            if not item.id:
                continue
            messages += 1
            translation = target.get(item.id)
            values = translation.string if translation else None
            complete = all(values) if isinstance(values, tuple) else bool(values)
            if not complete or "fuzzy" in translation.flags:
                label = " ".join(str(item.id).split())[:120]
                errors.append(f"{catalog.name}: missing or fuzzy translation: {label}")
    return errors, messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-root", type=Path, required=True)
    parser.add_argument("--gettext-root", type=Path, required=True)
    parser.add_argument(
        "--locale",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs/locale/en/LC_MESSAGES",
    )
    args = parser.parse_args()
    catalog_errors, messages = check_catalogs(args.gettext_root, args.locale)
    html_errors, pages = check_english_html(args.html_root)
    errors = catalog_errors + html_errors
    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"{messages} messages translated; {pages} English pages checked, including code examples and accessible labels."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

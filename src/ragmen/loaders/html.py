from __future__ import annotations

import re
from html.parser import HTMLParser

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIPPED = {"script", "style", "noscript", "template"}
BLOCK = {"p", "div", "li", "tr", "section", "article", "blockquote", "pre", "br"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._heading: int | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIPPED:
            self._skip_depth += 1
        elif tag in HEADING_LEVELS:
            self._break()
            self._heading = HEADING_LEVELS[tag]
            self._parts.append("#" * self._heading + " ")
        elif tag in BLOCK:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED and self._skip_depth:
            self._skip_depth -= 1
        elif tag in HEADING_LEVELS:
            self._break()
            self._heading = None
        elif tag in BLOCK:
            self._break()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            # HTML treats source newlines inside a paragraph as spaces.
            self._parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        return "".join(self._parts)

    def _break(self) -> None:
        self._parts.append("\n\n")


def html_to_text(markup: str) -> str:
    extractor = _Extractor()
    extractor.feed(markup)
    extractor.close()
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in extractor.text().splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

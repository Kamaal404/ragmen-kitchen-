from __future__ import annotations

from pathlib import Path

from ragmen.cook.segment import read_documents
from ragmen.loaders.html import html_to_text


def test_script_and_style_content_is_dropped() -> None:
    markup = "<html><head><style>p{color:red}</style><script>var x=1;</script></head><body><p>Keep me</p></body></html>"
    text = html_to_text(markup)
    assert "Keep me" in text
    assert "color" not in text
    assert "var x" not in text


def test_headings_become_markdown_headings_so_segmentation_sees_them() -> None:
    text = html_to_text("<h1>CHAPTER 1</h1><p>Body text.</p><h2>Section 1.1</h2><p>More.</p>")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[0] == "# CHAPTER 1"
    assert "## Section 1.1" in lines
    assert "Body text." in lines


def test_paragraphs_are_separated_by_blank_lines() -> None:
    text = html_to_text("<p>First paragraph.</p><p>Second paragraph.</p>")
    assert "First paragraph.\n\nSecond paragraph." in text


def test_entities_are_decoded_and_whitespace_collapsed() -> None:
    text = html_to_text("<p>Fire &amp; tinder   &#39;quoted&#39;\n   across lines</p>")
    assert text == "Fire & tinder 'quoted' across lines"


def test_read_documents_converts_html_and_keeps_text(tmp_path: Path) -> None:
    (tmp_path / "guide.html").write_text("<h1>Fire</h1><p>Use birch bark.</p>", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n\nPlain markdown.\n", encoding="utf-8")
    docs = dict(read_documents(tmp_path))
    html_doc = next(text for name, text in docs.items() if name.endswith("guide.html"))
    assert "<p>" not in html_doc
    assert "# Fire" in html_doc
    assert "Use birch bark." in html_doc
    assert any(name.endswith("notes.md") for name in docs)

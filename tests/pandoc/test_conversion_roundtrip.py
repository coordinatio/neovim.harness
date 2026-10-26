"""Round trips through Pandoc must keep a GFM table usable.

The HTML here is written by hand the way a browser or a web page writes it,
because Pandoc's own HTML writer sets every attribute the converter would
otherwise have to fall back on.
"""

from __future__ import annotations

import re

import pytest

from neovim_harness.assets import ConversionAssets
from neovim_harness.convert import HtmlToMarkdown, MarkdownToHtml


@pytest.fixture(scope="module")
def converters() -> tuple[MarkdownToHtml, HtmlToMarkdown]:
    assets = ConversionAssets.load()
    return MarkdownToHtml(assets.stylesheet), HtmlToMarkdown(assets.lua_filter)


def to_markdown(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown], html: str
) -> str:
    _, html_to_markdown = converters
    return html_to_markdown.convert(html.encode("utf-8"))


def to_html(converters: tuple[MarkdownToHtml, HtmlToMarkdown], markdown: str) -> str:
    markdown_to_html, _ = converters
    return markdown_to_html.convert(markdown)


def table(header: str, body: str, caption: str = "") -> str:
    caption_element = f"<caption>{caption}</caption>" if caption else ""
    return (
        f"<table>{caption_element}"
        f"<thead>{header}</thead>"
        f"<tbody>{body}</tbody>"
        f"</table>"
    )


def cell_texts(html: str) -> list[str]:
    return [
        re.sub(r"<[^>]*>", "", cell)
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", html, re.S)
    ]


def code_texts(html: str) -> list[str]:
    return re.findall(r"<code[^>]*>(.*?)</code>", html, re.S)


def footnote_reference(text: str) -> str:
    return (
        f'{text}<a href="#fn1" class="footnote-ref" id="fnref1" '
        'role="doc-noteref"><sup>1</sup></a>'
    )


def footnotes() -> str:
    return (
        '<section id="footnotes" class="footnotes footnotes-end-of-document" '
        'role="doc-endnotes"><hr><ol><li id="fn1"><p>note</p></li></ol></section>'
    )


def test_markdown_table_round_trip_preserves_cells_and_alignment(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    markdown = """# Heading

Text with **bold**, `code`, and [a link](https://example.com).

| Left | Center | Right |
| :--- | :----: | ---: |
| **a** | `b` | c |
| x\\|y | z |   |
"""

    html = to_html(converters, markdown)
    result = to_markdown(converters, html)

    assert "<table" in html
    assert "[TABLE]" not in result
    assert result == """# Heading

Text with **bold**, `code`, and [a link](https://example.com).

| Left | Center | Right |
| :--- | :---: | ---: |
| **a** | `b` | c |
| x\\|y | z |  |
"""


def test_every_header_row_is_kept(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Group</th><th>Value</th></tr>"
        "<tr><th>Item</th><th>Count</th></tr>",
        "<tr><td>a</td><td>1</td></tr>",
    )

    assert to_markdown(converters, html) == (
        "| Group | Value |\n| --- | --- |\n| Item | Count |\n| a | 1 |\n"
    )


def test_column_alignment_from_a_body_cell_is_kept(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    # Only the body cell carries the alignment, so it lives in the colspec.
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        '<tr><td>a</td><td align="right">10</td></tr>',
    )

    assert to_markdown(converters, html) == (
        "| Name | Amount |\n| --- | ---: |\n| a | 10 |\n"
    )


def test_caption_table_keeps_its_cells(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        "<tr><td>a</td><td>10</td></tr>",
        caption="Totals",
    )

    markdown = to_markdown(converters, html)

    assert "[TABLE]" not in markdown
    assert "Totals" in markdown
    assert "| a" in markdown and "10" in markdown


def test_span_table_keeps_its_cells(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        '<tr><td colspan="2">merged</td></tr><tr><td>a</td><td>10</td></tr>',
    )

    markdown = to_markdown(converters, html)

    assert "[TABLE]" not in markdown
    assert "merged" in markdown
    assert "| a" in markdown and "10" in markdown


def test_block_cell_falls_back_to_pandoc(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    # A GFM cell is inline-only.  Rather than write the block content as
    # inline text, the table is left to Pandoc, which says "[TABLE]".
    code = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        "<tr><td><pre><code>a\nb</code></pre></td><td>10</td></tr>",
    )
    items = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        "<tr><td><ul><li>a</li><li>b</li></ul></td><td>10</td></tr>",
    )

    for html in (code, items):
        markdown = to_markdown(converters, html)
        assert "[TABLE]" in markdown
        assert "```" not in markdown
        assert "- a<br>" not in markdown


def test_hard_break_cell_keeps_the_break(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        "<tr><td>one<br>two</td><td>10</td></tr>",
    )

    assert to_markdown(converters, html) == (
        "| Name | Amount |\n| --- | --- |\n| one<br>two | 10 |\n"
    )


def test_two_paragraph_cell_stays_in_the_fast_path(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        "<tr><td><p>one</p><p>two</p></td><td>10</td></tr>",
    )

    markdown = to_markdown(converters, html)

    assert "[TABLE]" not in markdown
    assert markdown == "| Name | Amount |\n| --- | --- |\n| one<br>two | 10 |\n"


def test_link_in_a_cell_stays_a_link(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    # A browser, and premailer in this very pipeline, put `style` and `class`
    # on links and spans.  A cell must still come out as plain Markdown.
    html = table(
        "<tr><th>Link</th><th>Text</th></tr>",
        '<tr><td><a href="https://c">c</a></td><td>d</td></tr>'
        '<tr><td><a href="https://c" style="color: red">c</a></td>'
        '<td><span class="kbd">K</span> <strong class="x">b</strong></td></tr>',
    )

    markdown = to_markdown(converters, html)

    assert markdown == (
        "| Link | Text |\n"
        "| --- | --- |\n"
        "| [c](https://c) | d |\n"
        "| [c](https://c) | K **b** |\n"
    )
    assert "<a " not in markdown
    assert "<span" not in markdown
    assert "style" not in markdown


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("<strong>a<br>b</strong>", "**a<br>b**"),
        ('<span style="font-weight:700">a<br>b</span>', "a<br>b"),
        ('<a href="https://x">a<br>b</a>', "[a<br>b](https://x)"),
        ("<del>a<br>b</del>", "~~a<br>b~~"),
    ],
)
def test_hard_break_inside_an_inline_container_stays_one_row(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
    cell: str,
    expected: str,
) -> None:
    html = table(
        "<tr><th>Name</th><th>Amount</th></tr>",
        f"<tr><td>{cell}</td><td>c</td></tr>",
    )

    markdown = to_markdown(converters, html)

    assert markdown == f"| Name | Amount |\n| --- | --- |\n| {expected} | c |\n"
    html_again = to_html(converters, markdown)
    # One row of two cells, and the break became HTML inside the cell instead
    # of a backslash and a newline that split the row.
    assert html_again.count("<tr") == 2
    assert html_again.count("<td") == 2
    assert "<br>" in html_again


def test_footnote_in_a_body_cell_is_left_to_pandoc(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = (
        table(
            "<tr><th>Name</th><th>Amount</th></tr>",
            f"<tr><td>{footnote_reference('a')}</td><td>b</td></tr>",
        )
        + footnotes()
    )

    markdown = to_markdown(converters, html)
    lines = markdown.splitlines()
    note_row = next(line for line in lines if "a[^1]" in line)

    # The cell after the reference keeps its text inside the table, and the
    # definition is written after the table rather than inside the row.
    assert "| b" in note_row
    assert lines.index("") > lines.index(note_row)
    assert markdown.rstrip().endswith("[^1]: note")
    assert cell_texts(to_html(converters, markdown))[1] == "b"


def test_footnote_in_a_header_cell_is_left_to_pandoc(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = (
        table(
            f"<tr><th>{footnote_reference('h')}</th><th>Amount</th></tr>",
            "<tr><td>a</td><td>b</td></tr>",
        )
        + footnotes()
    )

    markdown = to_markdown(converters, html)
    lines = markdown.splitlines()
    header_row = next(line for line in lines if "h[^1]" in line)

    assert "| Amount" in header_row
    assert lines.index("") > lines.index(header_row)
    assert markdown.rstrip().endswith("[^1]: note")
    assert cell_texts(to_html(converters, markdown)) == ["a", "b"]


def test_cell_ending_in_a_backslash_is_not_a_hard_break(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table("<tr><th>Path</th></tr>", "<tr><td>C:\\Users\\</td></tr>")

    assert to_markdown(converters, html) == "| Path |\n| --- |\n| C:\\Users\\\\ |\n"


def test_pipe_inside_a_code_span_does_not_end_the_cell(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Command</th><th>Note</th></tr>",
        "<tr><td><code>ps aux | grep x</code></td><td>y</td></tr>",
    )

    markdown = to_markdown(converters, html)

    assert markdown == (
        "| Command | Note |\n| --- | --- |\n| `ps aux | grep x` | y |\n"
    )
    # One row of two cells must come back, not three cells out of a split one.
    # The reader this project uses keeps a pipe inside a code span, so the cell
    # holds the original text and gains no backslash.
    html_again = to_html(converters, markdown)
    assert html_again.count("<td") == 2
    assert code_texts(html_again) == ["ps aux | grep x"]


def test_literal_backtick_before_a_code_span_does_not_hide_a_pipe(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    # The writer escapes a literal backtick, and that escaped backtick is not a
    # code span opener.  Pairing it with the real code span would leave the
    # pipe bare and split the row.
    html = table(
        "<tr><th>Command</th><th>Note</th></tr>",
        "<tr><td>a ` b <code>c|d</code></td><td>e</td></tr>",
    )

    markdown = to_markdown(converters, html)

    assert markdown == "| Command | Note |\n| --- | --- |\n| a \\` b `c|d` | e |\n"
    html_again = to_html(converters, markdown)
    assert html_again.count("<td") == 2
    assert code_texts(html_again) == ["c|d"]


def test_table_markdown_is_a_fixed_point(
    converters: tuple[MarkdownToHtml, HtmlToMarkdown],
) -> None:
    html = table(
        "<tr><th>Group</th><th>Value</th></tr><tr><th>Item</th><th>Count</th></tr>",
        "<tr><td>one<br>two</td><td><code>a|b</code></td></tr>"
        '<tr><td>foo\\</td>'
        '<td><a href="https://c" style="color: red">c</a></td></tr>',
    )

    first = to_markdown(converters, html)
    second = to_markdown(converters, to_html(converters, first))

    assert "[TABLE]" not in first
    assert second == first
    assert code_texts(to_html(converters, first)) == ["a|b"]
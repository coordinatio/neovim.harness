from neovim_harness.assets import ConversionAssets
from neovim_harness.convert import HtmlToMarkdown, MarkdownToHtml


def test_gfm_table_round_trip_preserves_cells_and_alignment() -> None:
    assets = ConversionAssets.load()
    markdown = """# Heading

Text with **bold**, `code`, and [a link](https://example.com).

| Left | Center | Right |
| :--- | :----: | ---: |
| **a** | `b` | [c](https://c) |
| x\\|y | z |   |
"""

    html = MarkdownToHtml(assets.stylesheet).convert(markdown)
    result = HtmlToMarkdown(assets.lua_filter).convert(html.encode("utf-8"))

    assert "<table" in html
    assert "[TABLE]" not in result
    assert result == """# Heading

Text with **bold**, `code`, and [a link](https://example.com).

| Left | Center | Right |
| :--- | :---: | ---: |
| **a** | `b` | [c](https://c) |
| x\\|y | z |  |
"""

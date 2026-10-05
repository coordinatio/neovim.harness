from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from lxml import html as lxml_html

from neovim_harness.convert import HtmlToMarkdown, MarkdownToHtml


def _completed(stdout: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(["pandoc"], 0, stdout=stdout, stderr=b"")


def test_empty_html_skips_pandoc(tmp_path: Path) -> None:
    assert HtmlToMarkdown(tmp_path / "backics.lua").convert(b"") == ""


def test_html_to_markdown_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lua = tmp_path / "filters" / "backics.lua"
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return _completed(b"# title\n")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    result = HtmlToMarkdown(lua).convert(b"<p>title</p>")
    assert result == "# title\n"
    assert seen["command"] == [
        "pandoc",
        "-f",
        "html",
        "-t",
        "gfm-raw_html",
        "--wrap=none",
        f"--lua-filter={lua}",
    ]
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["input"] == b"<p>title</p>"
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is True


def test_html_to_markdown_pandoc_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr=b"no filter\n")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    assert HtmlToMarkdown(tmp_path / "backics.lua").convert(b"<p>x</p>") == ""
    assert "Pandoc html_to_gfm failed: no filter\n" in caplog.text


def test_markdown_to_html_arguments_and_body_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    css = tmp_path / "github-pandoc.css"
    inlined = "<html><head><title>t</title></head><body><p>Hi</p><p>There</p></body></html>"
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return _completed(b"<html>raw</html>")

    def fake_transform(html: str, remove_classes: bool = False) -> str:
        seen["remove_classes"] = remove_classes
        seen["transformed_from"] = html
        return inlined

    levels: list[int] = []
    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr("neovim_harness.convert.premailer_transform", fake_transform)
    monkeypatch.setattr(
        "neovim_harness.convert.cssutils.log.setLevel",
        lambda level: levels.append(level),
    )
    result = MarkdownToHtml(css).convert("hello")
    assert seen["command"] == [
        "pandoc",
        "-f",
        "markdown+hard_line_breaks+lists_without_preceding_blankline",
        "-c",
        str(css),
        "--embed-resources",
        "--standalone",
    ]
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["input"] == b"hello"
    assert seen["remove_classes"] is True
    assert seen["transformed_from"] == "<html>raw</html>"
    assert logging.CRITICAL in levels
    expected = "".join(
        lxml_html.tostring(child, encoding="unicode")
        for child in lxml_html.fromstring(inlined).find("body")
    )
    assert result == expected
    assert "<html" not in result
    assert "<body" not in result


def test_pandoc_launch_and_stdout_errors_return_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("pandoc")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", missing)
    assert HtmlToMarkdown(tmp_path / "backics.lua").convert(b"<p>x</p>") == ""

    def bad_stdout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 0, stdout=b"\xff", stderr=b"")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", bad_stdout)
    assert MarkdownToHtml(tmp_path / "github-pandoc.css").convert("x") == ""


def test_non_utf8_pandoc_stderr_returns_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr=b"\xff")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    assert HtmlToMarkdown(tmp_path / "backics.lua").convert(b"<p>x</p>") == ""
    assert MarkdownToHtml(tmp_path / "github-pandoc.css").convert("x") == ""
    assert "\ufffd" in caplog.text


def test_markdown_pandoc_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr=b"bad md")

    def fake_transform(*args: object, **kwargs: object) -> str:
        raise AssertionError("premailer should not run")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr("neovim_harness.convert.premailer_transform", fake_transform)
    caplog.set_level(logging.ERROR)
    assert MarkdownToHtml(tmp_path / "github-pandoc.css").convert("x") == ""
    assert "Pandoc failed: bad md" in caplog.text


def test_premailer_failure_returns_pandoc_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return _completed(b"<html>raw</html>")

    def fake_transform(*args: object, **kwargs: object) -> str:
        raise RuntimeError("css broke")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr("neovim_harness.convert.premailer_transform", fake_transform)
    caplog.set_level(logging.ERROR)
    assert MarkdownToHtml(tmp_path / "style.css").convert("x") == "<html>raw</html>"
    assert "Premailer failed: css broke" in caplog.text


def test_lxml_failure_returns_inlined_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inlined = "<html><body><p>inlined</p></body></html>"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return _completed(b"<html>raw</html>")

    def fake_fromstring(html: str) -> object:
        raise RuntimeError("bad xml")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr(
        "neovim_harness.convert.premailer_transform",
        lambda html, remove_classes=False: inlined,
    )
    monkeypatch.setattr("neovim_harness.convert.lxml_html.fromstring", fake_fromstring)
    caplog.set_level(logging.ERROR)
    assert MarkdownToHtml(tmp_path / "style.css").convert("x") == inlined
    assert "XML parsing failed: bad xml" in caplog.text


def test_missing_body_returns_inlined_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inlined = "<div>only</div>"

    class Tree:
        def find(self, tag: str) -> None:
            return None

    monkeypatch.setattr(
        "neovim_harness.convert.subprocess.run",
        lambda *args, **kwargs: _completed(b"<html>raw</html>"),
    )
    monkeypatch.setattr(
        "neovim_harness.convert.premailer_transform",
        lambda html, remove_classes=False: inlined,
    )
    monkeypatch.setattr(
        "neovim_harness.convert.lxml_html.fromstring",
        lambda html: Tree(),
    )
    assert MarkdownToHtml(tmp_path / "style.css").convert("x") == inlined

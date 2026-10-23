from __future__ import annotations

import logging
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from lxml import html as lxml_html

from neovim_harness.convert import ConversionError, HtmlToMarkdown, MarkdownToHtml


def _completed(stdout: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(["pandoc"], 0, stdout=stdout, stderr=b"")


def test_empty_html_skips_pandoc(tmp_path: Path) -> None:
    converter = HtmlToMarkdown(tmp_path / "backics.lua")
    assert converter.convert(b"") == ""
    assert converter.convert_strict(b"") == ""


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
    assert "timeout" not in kwargs
    strict = HtmlToMarkdown(lua).convert_strict(b"<p>title</p>")
    assert strict == "# title\n"
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
    assert kwargs["timeout"] == 30


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
    assert "timeout" not in kwargs
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
    MarkdownToHtml(css).convert_strict("hello")
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
    assert kwargs["timeout"] == 30
    assert seen["remove_classes"] is True


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


def test_strict_html_conversion_reports_pandoc_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr=b"no filter\n")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    converter = HtmlToMarkdown(tmp_path / "backics.lua")
    with pytest.raises(ConversionError, match="Pandoc html_to_gfm failed: no filter"):
        converter.convert_strict(b"<p>x</p>")
    assert converter.convert(b"<p>x</p>") == ""


def test_strict_markdown_conversion_reports_pandoc_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr=b"bad md")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    converter = MarkdownToHtml(tmp_path / "github-pandoc.css")
    with pytest.raises(ConversionError, match="Pandoc failed: bad md"):
        converter.convert_strict("x")
    assert converter.convert("x") == ""


def test_strict_markdown_conversion_keeps_premailer_and_lxml_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inlined = "<html><body><p>inlined</p></body></html>"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return _completed(b"<html>raw</html>")

    def broken_premailer(*args: object, **kwargs: object) -> str:
        raise RuntimeError("css broke")

    def broken_xml(html: str) -> object:
        raise RuntimeError("bad xml")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr("neovim_harness.convert.premailer_transform", broken_premailer)
    assert MarkdownToHtml(tmp_path / "style.css").convert_strict("x") == "<html>raw</html>"

    monkeypatch.setattr(
        "neovim_harness.convert.premailer_transform",
        lambda html, remove_classes=False: inlined,
    )
    monkeypatch.setattr("neovim_harness.convert.lxml_html.fromstring", broken_xml)
    assert MarkdownToHtml(tmp_path / "style.css").convert_strict("x") == inlined


def test_pandoc_failure_detail_accepts_text_and_missing_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def text_stderr(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0], stderr="plain text")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", text_stderr)
    with pytest.raises(ConversionError, match="Pandoc failed: plain text"):
        MarkdownToHtml(tmp_path / "style.css").convert_strict("x")

    def missing_stderr(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", missing_stderr)
    with pytest.raises(ConversionError, match=r"Pandoc html_to_gfm failed:\s*$"):
        HtmlToMarkdown(tmp_path / "backics.lua").convert_strict(b"<p>x</p>")


def test_pandoc_timeout_is_a_strict_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    timeouts: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        timeouts.append(kwargs["timeout"] if "timeout" in kwargs else None)
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 30))

    def explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("premailer should not run")

    monkeypatch.setattr("neovim_harness.convert.subprocess.run", fake_run)
    monkeypatch.setattr("neovim_harness.convert.premailer_transform", explode)
    caplog.set_level(logging.ERROR)
    html = HtmlToMarkdown(tmp_path / "backics.lua")
    with pytest.raises(ConversionError) as html_error:
        html.convert_strict(b"<p>x</p>")
    assert str(html_error.value) == "Timed out waiting for pandoc."
    with pytest.raises(subprocess.TimeoutExpired):
        html.convert(b"<p>x</p>")
    markdown = MarkdownToHtml(tmp_path / "style.css")
    with pytest.raises(ConversionError) as markdown_error:
        markdown.convert_strict("x")
    assert str(markdown_error.value) == "Timed out waiting for pandoc."
    with pytest.raises(subprocess.TimeoutExpired):
        markdown.convert("x")
    assert timeouts == [30, None, 30, None]
    assert "Timed out waiting for pandoc." not in caplog.text


def test_markdown_conversion_loads_premailer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def transform(html: str, remove_classes: bool = False) -> str:
        captured["html"] = html
        captured["remove_classes"] = remove_classes
        return "<html><body><p>Hi</p></body></html>"

    fake = types.ModuleType("premailer")
    fake.transform = transform
    monkeypatch.setitem(sys.modules, "premailer", fake)
    monkeypatch.setattr(
        "neovim_harness.convert.subprocess.run",
        lambda *args, **kwargs: _completed(b"<html>raw</html>"),
    )
    result = MarkdownToHtml(tmp_path / "style.css").convert_strict("x")
    assert captured == {"html": "<html>raw</html>", "remove_classes": True}
    assert "Hi" in result
    assert "<html" not in result


def test_importing_convert_does_not_import_html_libraries() -> None:
    root = Path(__file__).resolve().parents[2]
    script = """
import sys
import neovim_harness.convert
from neovim_harness.convert import HtmlToMarkdown
from neovim_harness.environment import collect_html_to_markdown_failures
HtmlToMarkdown("backics.lua")
collect_html_to_markdown_failures()
for name in ("lxml", "premailer", "cssutils"):
    assert name not in sys.modules, name
"""
    # Unit tests replace subprocess.run. Popen stays available for this interpreter.
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stdout + stderr


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

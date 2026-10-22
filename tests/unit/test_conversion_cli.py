from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from neovim_harness.cli import main
from neovim_harness.clipboard import ClipboardError
from neovim_harness.convert import ConversionError
from neovim_harness.environment import SUCCESS_TEXT, RequirementFailure, format_report


class _Input:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class _Clipboard:
    def __init__(self) -> None:
        self.required: list[str] = []
        self.payload = b"<p>Hi</p>"
        self.writes: list[tuple[str, str]] = []
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None

    def read_required(self, mimetype: str) -> bytes:
        self.required.append(mimetype)
        if self.read_error is not None:
            raise self.read_error
        return self.payload

    def write(self, data: str, mimetype: str = "text/plain") -> None:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append((data, mimetype))


class _Result:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[object] = []
        self.error: Exception | None = None


def _install(
    monkeypatch: pytest.MonkeyPatch,
    clipboard: _Clipboard,
    html: _Result,
    markdown: _Result,
) -> None:
    class Html:
        def __init__(self, path: Path) -> None:
            self.path = path

        def convert_strict(self, html_content: bytes) -> str:
            html.calls.append(html_content)
            if html.error is not None:
                raise html.error
            return html.text

    class Markdown:
        def __init__(self, path: Path) -> None:
            self.path = path

        def convert_strict(self, markdown_content: str) -> str:
            markdown.calls.append(markdown_content)
            if markdown.error is not None:
                raise markdown.error
            return markdown.text

    def forbid_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("session created")

    def forbid_full_check() -> None:
        raise AssertionError("full environment check")

    monkeypatch.setattr("neovim_harness.cli.collect_conversion_failures", lambda: [])
    monkeypatch.setattr("neovim_harness.cli.collect_failures", forbid_full_check)
    monkeypatch.setattr("neovim_harness.sessions.SessionStore", forbid_session)
    monkeypatch.setattr("neovim_harness.clipboard.WaylandClipboard", lambda: clipboard)
    monkeypatch.setattr("neovim_harness.convert.HtmlToMarkdown", Html)
    monkeypatch.setattr("neovim_harness.convert.MarkdownToHtml", Markdown)


def test_clipboard_to_markdown_writes_stdout_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    html = _Result("héllo\n")
    markdown = _Result("<p>unused</p>")
    _install(monkeypatch, clipboard, html, markdown)
    main(["--clipboard-to-markdown"])
    captured = capsys.readouterr()
    assert captured.out == "héllo\n"
    assert captured.err == ""
    assert clipboard.required == ["text/html"]
    assert clipboard.writes == []
    assert html.calls == [b"<p>Hi</p>"]
    assert markdown.calls == []


def test_markdown_to_clipboard_reads_stdin_and_leaves_stdout_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    html = _Result("unused")
    markdown = _Result("<p>héllo</p>")
    _install(monkeypatch, clipboard, html, markdown)
    monkeypatch.setattr(sys, "stdin", _Input("# Title\n".encode()))
    main(["--markdown-to-clipboard"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert markdown.calls == ["# Title\n"]
    assert clipboard.writes == [("<p>héllo</p>", "text/html")]
    assert clipboard.required == []
    assert html.calls == []


def test_empty_html_writes_empty_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    clipboard.payload = b""
    html = _Result("")
    _install(monkeypatch, clipboard, html, _Result(""))
    main(["--clipboard-to-markdown"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert html.calls == [b""]


def test_missing_html_is_an_error_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    clipboard.read_error = ClipboardError("The clipboard has no text/html content.")
    html = _Result("nope")
    _install(monkeypatch, clipboard, html, _Result(""))
    with pytest.raises(SystemExit) as caught:
        main(["--clipboard-to-markdown"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "The clipboard has no text/html content.\n"
    assert "Traceback" not in captured.err
    assert html.calls == []


def test_pandoc_failure_is_an_error_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    html = _Result("")
    html.error = ConversionError("Pandoc html_to_gfm failed: bad html")
    _install(monkeypatch, clipboard, html, _Result(""))
    with pytest.raises(SystemExit) as caught:
        main(["--clipboard-to-markdown"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Pandoc html_to_gfm failed: bad html\n"
    assert clipboard.writes == []


def test_clipboard_write_failure_does_not_print_html(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    clipboard.write_error = subprocess.CalledProcessError(1, ["wl-copy"])
    markdown = _Result("<p>styled</p>")
    _install(monkeypatch, clipboard, _Result(""), markdown)
    monkeypatch.setattr(sys, "stdin", _Input(b"hello"))
    with pytest.raises(SystemExit) as caught:
        main(["--markdown-to-clipboard"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Could not copy text/html to the clipboard.\n"
    assert markdown.calls == ["hello"]
    assert clipboard.writes == []


def test_missing_wl_copy_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clipboard = _Clipboard()
    clipboard.write_error = FileNotFoundError("wl-copy")
    _install(monkeypatch, clipboard, _Result(""), _Result("<p>x</p>"))
    monkeypatch.setattr(sys, "stdin", _Input(b"hello"))
    with pytest.raises(SystemExit) as caught:
        main(["--markdown-to-clipboard"])
    assert caught.value.code == 1
    assert capsys.readouterr().err == "The wl-copy command is not on PATH.\n"


def test_invalid_utf8_does_not_convert(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown = _Result("<p>x</p>")
    _install(monkeypatch, _Clipboard(), _Result(""), markdown)
    monkeypatch.setattr(sys, "stdin", _Input(b"\xff"))
    with pytest.raises(SystemExit) as caught:
        main(["--markdown-to-clipboard"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Markdown from stdin is not valid UTF-8.\n"
    assert markdown.calls == []


def test_conversion_check_failure_stays_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RequirementFailure(
        "pandoc",
        "The pandoc command is not on PATH.\nInstall the pandoc-cli package.",
    )

    def forbid_clipboard() -> None:
        raise AssertionError("clipboard opened")

    monkeypatch.setattr("neovim_harness.cli.collect_conversion_failures", lambda: [failure])
    monkeypatch.setattr("neovim_harness.clipboard.WaylandClipboard", forbid_clipboard)
    with pytest.raises(SystemExit) as caught:
        main(["--clipboard-to-markdown"])
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == format_report([failure])


def test_check_environment_stays_the_full_check_with_a_helper_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbid_conversion_check() -> None:
        raise AssertionError("conversion check")

    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [])
    monkeypatch.setattr(
        "neovim_harness.cli.collect_conversion_failures",
        forbid_conversion_check,
    )
    with pytest.raises(SystemExit) as caught:
        main(["--markdown-to-clipboard", "--check-environment"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"{SUCCESS_TEXT}\n"

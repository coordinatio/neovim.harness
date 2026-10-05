from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest

from neovim_harness.app import App
from neovim_harness.convert import HtmlToMarkdown
from neovim_harness.modes import (
    EditFormattedText,
    EditPlainText,
    NewFormattedText,
    NewPlainText,
    Workflow,
)
from neovim_harness.sessions import SessionStore

_WHEN = datetime(2026, 10, 5, 14, 18, 3)
_WHEN_NAME = "doc-261005141803"


class FakeClipboard:
    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []

    def read(self, mimetype: str = "") -> bytes:
        self.reads.append(mimetype)
        return self.payload

    def write(self, data: str, mimetype: str = "text/plain") -> None:
        self.writes.append((data, mimetype))


class FakeHtml:
    def __init__(self, text: str = "converted markdown") -> None:
        self.text = text
        self.calls: list[bytes] = []

    def convert(self, html_content: bytes) -> str:
        self.calls.append(html_content)
        return self.text


class FakeMarkdown:
    def __init__(self, text: str = "<p>styled</p>") -> None:
        self.text = text
        self.calls: list[str] = []

    def convert(self, markdown_content: str) -> str:
        self.calls.append(markdown_content)
        return self.text


class FakeEditor:
    def __init__(self, replacement: str | None = "edited", delete: bool = False) -> None:
        self.replacement = replacement
        self.delete = delete
        self.calls: list[tuple[Path, list[str]]] = []
        self.modes: list[int] = []
        self.contents: list[str] = []

    def open(self, file_path: Path, ex_commands: list[str]) -> None:
        self.calls.append((file_path, list(ex_commands)))
        self.modes.append(file_path.stat().st_mode & 0o777)
        self.contents.append(file_path.read_text(encoding="utf-8"))
        if self.delete:
            file_path.unlink()
            return
        if self.replacement is not None:
            file_path.write_text(self.replacement, encoding="utf-8")


def _run(
    tmp_path: Path,
    mode: Workflow,
    clipboard: FakeClipboard,
    editor: FakeEditor,
    html: FakeHtml | HtmlToMarkdown,
    markdown: FakeMarkdown,
) -> Path:
    app = App(
        sessions=SessionStore(tmp_path, clock=lambda: _WHEN),
        mode=mode,
        clipboard=clipboard,
        editor=editor,
        html_to_markdown=html,
        markdown_to_html=markdown,
    )
    app.run()
    assert editor.calls
    return editor.calls[0][0]


def test_four_modes(tmp_path: Path) -> None:
    cases: list[dict[str, object]] = [
        {
            "mode": NewPlainText(),
            "payload": b"",
            "reads": [],
            "before": "",
            "commands": ["+start"],
            "html_calls": [],
            "md_calls": [],
            "writes": [("edited", "text/plain")],
        },
        {
            "mode": EditPlainText(),
            "payload": b"pasted",
            "reads": [""],
            "before": "pasted",
            "commands": [],
            "html_calls": [],
            "md_calls": [],
            "writes": [("edited", "text/plain")],
        },
        {
            "mode": EditFormattedText(),
            "payload": b"<p>x</p>",
            "reads": ["text/html"],
            "before": "converted markdown",
            "commands": ["+colorscheme retrobox"],
            "html_calls": [b"<p>x</p>"],
            "md_calls": ["edited"],
            "writes": [("<p>styled</p>", "text/html")],
        },
        {
            "mode": NewFormattedText(),
            "payload": b"",
            "reads": [],
            "before": "",
            "commands": ["+start", "+colorscheme retrobox"],
            "html_calls": [],
            "md_calls": ["edited"],
            "writes": [("<p>styled</p>", "text/html")],
        },
    ]
    for case in cases:
        mode = case["mode"]
        assert isinstance(mode, (NewPlainText, EditPlainText, EditFormattedText, NewFormattedText))
        root = tmp_path / type(mode).__name__
        root.mkdir()
        payload = case["payload"]
        assert isinstance(payload, bytes)
        clipboard = FakeClipboard(payload)
        html = FakeHtml()
        markdown = FakeMarkdown()
        editor = FakeEditor()
        path = _run(root, mode, clipboard, editor, html, markdown)
        assert path.parent.name == _WHEN_NAME
        assert path.name == f"{_WHEN_NAME}.md"
        assert editor.calls[0][1] == case["commands"]
        assert editor.contents == [case["before"]]
        assert editor.modes == [0o600]
        assert clipboard.reads == case["reads"]
        assert clipboard.writes == case["writes"]
        assert html.calls == case["html_calls"]
        assert markdown.calls == case["md_calls"]
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600


def test_missing_session_file_does_not_write_the_clipboard(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clipboard = FakeClipboard()
    editor = FakeEditor(delete=True)
    caplog.set_level(logging.WARNING)
    path = _run(tmp_path, NewPlainText(), clipboard, editor, FakeHtml(), FakeMarkdown())
    assert clipboard.writes == []
    assert path.parent.exists()
    assert not path.exists()
    assert (
        "Temporary file not found (maybe editor didn't save?). Exiting."
        in caplog.text
    )


def test_empty_html_clipboard_becomes_an_empty_markdown_file(tmp_path: Path) -> None:
    clipboard = FakeClipboard(b"")
    editor = FakeEditor(replacement=None)
    path = _run(
        tmp_path,
        EditFormattedText(),
        clipboard,
        editor,
        HtmlToMarkdown(tmp_path / "backics.lua"),
        FakeMarkdown(),
    )
    assert clipboard.reads == ["text/html"]
    assert editor.contents == [""]
    assert path.read_text(encoding="utf-8") == ""

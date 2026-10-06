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
from neovim_harness.workspace import (
    ClipboardSessionSource,
    SessionLifecycle,
    new_rename_request,
)

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

    def open(
        self,
        directory: Path,
        ex_commands: list[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        assert file_path is not None
        assert directory == file_path.parent
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
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    app = App(
        source=ClipboardSessionSource(store),
        mode=mode,
        clipboard=clipboard,
        editor=editor,
        html_to_markdown=html,
        markdown_to_html=markdown,
        lifecycle=SessionLifecycle(store, _RejectGit()),
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


class _RejectGit:
    def init(self, directory: Path) -> None:
        raise AssertionError(directory)


class _RecordingGit:
    def __init__(self) -> None:
        self.directories: list[Path] = []

    def init(self, directory: Path) -> None:
        self.directories.append(directory)
        (directory / ".git").mkdir()


class _RenameOnce:
    def __init__(self) -> None:
        self.opens = 0

    def open(
        self,
        directory: Path,
        ex_commands: list[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        assert file_path is not None
        self.opens += 1
        if self.opens == 1:
            file_path.write_text("kept", encoding="utf-8")
            rename_request.write_text("Later", encoding="utf-8")
            return
        assert self.opens == 2
        assert directory.name == f"{_WHEN_NAME}--Later"
        assert file_path == directory / f"{directory.name}.md"
        assert ex_commands == ["+start"]
        assert file_path.read_text(encoding="utf-8") == "kept"


class _Dialogs:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, text: str) -> None:
        self.errors.append(text)


class _InvalidThenQuit:
    def __init__(self) -> None:
        self.opens = 0

    def open(
        self,
        directory: Path,
        ex_commands: list[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        assert file_path is not None
        self.opens += 1
        file_path.write_text("edited", encoding="utf-8")
        if self.opens == 1:
            assert directory.name == _WHEN_NAME
            rename_request.write_text("///", encoding="utf-8")
            return
        assert directory.name == _WHEN_NAME


def test_rename_reopens_without_copying_to_the_clipboard(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    git = _RecordingGit()
    editor = _RenameOnce()
    clipboard = FakeClipboard()
    dialogs = _Dialogs()
    App(
        source=ClipboardSessionSource(store),
        mode=NewPlainText(),
        clipboard=clipboard,
        editor=editor,
        html_to_markdown=FakeHtml(),
        markdown_to_html=FakeMarkdown(),
        lifecycle=SessionLifecycle(store, git, dialogs),
    ).run()
    assert editor.opens == 2
    assert clipboard.writes == []
    assert dialogs.errors == []
    assert git.directories[0].name == f"{_WHEN_NAME}--Later"
    assert (git.directories[0] / ".git").is_dir()
    assert not (tmp_path / _WHEN_NAME).exists()
    document = git.directories[0] / f"{_WHEN_NAME}--Later.md"
    assert document.read_text(encoding="utf-8") == "kept"
    assert document.stat().st_mode & 0o777 == 0o600


class _DeleteThenRename:
    def __init__(self) -> None:
        self.opens: list[tuple[Path, Path | None]] = []

    def open(
        self,
        directory: Path,
        ex_commands: list[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        self.opens.append((directory, file_path))
        if len(self.opens) == 1:
            assert file_path is not None
            assert file_path.is_file()
            file_path.unlink()
            rename_request.write_text("Later", encoding="utf-8")
            return
        assert ex_commands == ["+start"]
        assert directory.name == f"{_WHEN_NAME}--Later"
        assert file_path is None


def test_deleted_clipboard_file_reopens_without_a_path(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    editor = _DeleteThenRename()
    clipboard = FakeClipboard()
    App(
        source=ClipboardSessionSource(store),
        mode=NewPlainText(),
        clipboard=clipboard,
        editor=editor,
        html_to_markdown=FakeHtml(),
        markdown_to_html=FakeMarkdown(),
        lifecycle=SessionLifecycle(store, _RecordingGit(), _Dialogs()),
    ).run()
    assert len(editor.opens) == 2
    renamed = tmp_path / f"{_WHEN_NAME}--Later"
    assert editor.opens[1] == (renamed, None)
    assert clipboard.writes == []
    assert not (tmp_path / _WHEN_NAME).exists()
    assert list(renamed.glob("*.md")) == []


def test_unusable_rename_reopens_the_same_directory(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    editor = _InvalidThenQuit()
    clipboard = FakeClipboard()
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    App(
        source=ClipboardSessionSource(store),
        mode=NewPlainText(),
        clipboard=clipboard,
        editor=editor,
        html_to_markdown=FakeHtml(),
        markdown_to_html=FakeMarkdown(),
        lifecycle=SessionLifecycle(store, _RejectGit(), dialogs),
    ).run()
    assert editor.opens == 2
    assert clipboard.writes == [("edited", "text/plain")]
    assert (tmp_path / _WHEN_NAME).is_dir()
    assert "That session name cannot be used in a folder name." in caplog.text
    assert dialogs.errors == ["That session name cannot be used in a folder name."]


def test_editor_failure_removes_the_rename_request_directory(tmp_path: Path) -> None:
    class Boom:
        def __init__(self) -> None:
            self.request: Path | None = None

        def open(
            self,
            directory: Path,
            ex_commands: list[str],
            file_path: Path | None,
            rename_request: Path,
        ) -> None:
            self.request = rename_request
            rename_request.write_text("Later", encoding="utf-8")
            raise SystemExit(1)

    editor = Boom()
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    with pytest.raises(SystemExit) as caught:
        App(
            source=ClipboardSessionSource(store),
            mode=NewPlainText(),
            clipboard=FakeClipboard(),
            editor=editor,
            html_to_markdown=FakeHtml(),
            markdown_to_html=FakeMarkdown(),
            lifecycle=SessionLifecycle(store, _RejectGit(), _Dialogs()),
        ).run()
    assert caught.value.code == 1
    assert editor.request is not None
    assert not editor.request.exists()
    assert not editor.request.parent.exists()
    assert (tmp_path / _WHEN_NAME).is_dir()


def test_prepare_failure_removes_the_rename_request_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Path] = []

    def remember() -> Path:
        path = new_rename_request()
        requests.append(path)
        return path

    monkeypatch.setattr("neovim_harness.workspace.new_rename_request", remember)

    class FailPrepare:
        def prepare(
            self,
            path: Path | None,
            clipboard: FakeClipboard,
            html_to_markdown: FakeHtml,
        ) -> None:
            raise OSError("clipboard failed")

        def ex_commands(self) -> list[str]:
            return []

        def publish(
            self,
            content: str,
            clipboard: FakeClipboard,
            markdown_to_html: FakeMarkdown,
        ) -> None:
            raise AssertionError(content)

    class Editor:
        def open(
            self,
            directory: Path,
            ex_commands: list[str],
            file_path: Path | None,
            rename_request: Path,
        ) -> None:
            raise AssertionError(directory)

    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    with pytest.raises(OSError, match="clipboard failed"):
        App(
            source=ClipboardSessionSource(store),
            mode=FailPrepare(),
            clipboard=FakeClipboard(),
            editor=Editor(),
            html_to_markdown=FakeHtml(),
            markdown_to_html=FakeMarkdown(),
            lifecycle=SessionLifecycle(store, _RejectGit(), _Dialogs()),
        ).run()
    assert len(requests) == 1
    assert not requests[0].exists()
    assert not requests[0].parent.exists()
    assert (tmp_path / _WHEN_NAME).is_dir()


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

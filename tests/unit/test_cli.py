from __future__ import annotations

import logging
import runpy
import sys
from pathlib import Path

import pytest

from neovim_harness.cli import main
from neovim_harness.environment import SUCCESS_TEXT, RequirementFailure, format_report


class FakeClipboard:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []

    def read(self, mimetype: str = "") -> bytes:
        self.reads.append(mimetype)
        return b"<p>clip</p>" if mimetype == "text/html" else b"plain clip"

    def write(self, data: str, mimetype: str = "text/plain") -> None:
        self.writes.append((data, mimetype))


class FakeEditor:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.files: list[Path | None] = []
        self.directories: list[Path] = []
        self.picks: list[tuple[Path, Path]] = []

    def open(
        self,
        directory: Path,
        ex_commands: list[str],
        file_path: Path | None,
        rename_request: Path,
    ) -> None:
        self.commands.append(list(ex_commands))
        self.files.append(file_path)
        self.directories.append(directory)
        if file_path is not None:
            file_path.write_text("from editor", encoding="utf-8")

    def pick(self, catalog_path: Path, choice_path: Path) -> int:
        self.picks.append((catalog_path, choice_path))
        return 0


class FakeHtml:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[bytes] = []

    def convert(self, html_content: bytes) -> str:
        self.calls.append(html_content)
        return "from html"


class FakeMarkdown:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[str] = []

    def convert(self, markdown_content: str) -> str:
        self.calls.append(markdown_content)
        return "<p>from markdown</p>"


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    clipboard = FakeClipboard()
    editor = FakeEditor()
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [])
    monkeypatch.setattr(
        "neovim_harness.sessions.sessions_root",
        lambda environ, home: tmp_path,
    )
    monkeypatch.setattr("neovim_harness.clipboard.WaylandClipboard", lambda: clipboard)
    monkeypatch.setattr(
        "neovim_harness.editor.NeovideEditor",
        lambda *args, **kwargs: editor,
    )
    monkeypatch.setattr("neovim_harness.convert.HtmlToMarkdown", FakeHtml)
    monkeypatch.setattr("neovim_harness.convert.MarkdownToHtml", FakeMarkdown)
    return {"clipboard": clipboard, "editor": editor, "root": tmp_path}


def test_help_lists_the_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["-h"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "named session" in output
    for flag in (
        "-p",
        "-m",
        "-n",
        "-s",
        "--session",
        "-r",
        "--resume",
        "--check-environment",
        "--verbose",
    ):
        assert flag in output


@pytest.mark.parametrize(
    "argv",
    [
        ["-p", "-m"],
        ["-s", "-r"],
        ["-s", "-p"],
        ["-n", "--resume"],
    ],
)
def test_mode_flags_are_mutually_exclusive(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 2


def test_check_environment_prints_success_and_does_not_open_the_editor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [])
    with pytest.raises(SystemExit) as caught:
        main(["-m", "--check-environment"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"{SUCCESS_TEXT}\n"


def test_check_environment_prints_the_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RequirementFailure("neovide", "The neovide command is not on PATH.\nInstall the neovide package.")
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [failure])
    with pytest.raises(SystemExit) as caught:
        main(["--check-environment"])
    assert caught.value.code == 1
    captured = capsys.readouterr().out
    assert captured == format_report([failure])
    assert SUCCESS_TEXT not in captured


def test_startup_check_failure_does_not_create_a_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = RequirementFailure(
        "Wayland session",
        "WAYLAND_DISPLAY is not set.\nRun this install from a Wayland session.",
    )
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [failure])

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("session created")

    monkeypatch.setattr("neovim_harness.sessions.SessionStore", boom)
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 1
    assert capsys.readouterr().out == format_report([failure])


@pytest.mark.parametrize(
    ("argv", "commands", "read_mime", "write"),
    [
        ([], ["+start"], None, ("from editor", "text/plain")),
        (["-p"], [], "", ("from editor", "text/plain")),
        (["-m"], ["+colorscheme retrobox"], "text/html", ("<p>from markdown</p>", "text/html")),
        (
            ["-n"],
            ["+start", "+colorscheme retrobox"],
            None,
            ("<p>from markdown</p>", "text/html"),
        ),
    ],
)
def test_main_wires_each_mode(
    runtime: dict[str, object],
    argv: list[str],
    commands: list[str],
    read_mime: str | None,
    write: tuple[str, str],
) -> None:
    main(argv)
    clipboard = runtime["clipboard"]
    editor = runtime["editor"]
    root = runtime["root"]
    assert isinstance(clipboard, FakeClipboard)
    assert isinstance(editor, FakeEditor)
    assert isinstance(root, Path)
    assert editor.commands == [commands]
    if read_mime is None:
        assert clipboard.reads == []
    else:
        assert clipboard.reads == [read_mime]
    assert clipboard.writes == [write]
    sessions = [path for path in root.iterdir() if path.is_dir()]
    assert len(sessions) == 1
    assert sessions[0].parent == root


def test_verbose_flag_sets_debug_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [])
    logger = logging.getLogger("neovim_harness")
    try:
        with pytest.raises(SystemExit) as caught:
            main(["-v", "--check-environment"])
        assert caught.value.code == 0
        assert logger.level == logging.DEBUG
        assert capsys.readouterr().out == f"{SUCCESS_TEXT}\n"
    finally:
        logger.setLevel(logging.INFO)


def test_named_session_does_not_use_the_clipboard(
    runtime: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    created: list[Path] = []

    def ask(self: object, text: str) -> str:
        prompts.append(text)
        return "Fix login"

    def init(self: object, directory: Path) -> None:
        created.append(directory)
        (directory / ".git").mkdir()

    monkeypatch.setattr("neovim_harness.prompt.KDialogPrompt.ask", ask)
    monkeypatch.setattr("neovim_harness.repository.GitRepository.init", init)
    main(["-s"])
    editor = runtime["editor"]
    clipboard = runtime["clipboard"]
    root = runtime["root"]
    assert isinstance(editor, FakeEditor)
    assert isinstance(clipboard, FakeClipboard)
    assert isinstance(root, Path)
    assert prompts[0].startswith("Name this session")
    assert editor.commands == [["+start"]]
    assert editor.files == [None]
    assert clipboard.reads == []
    assert clipboard.writes == []
    assert len(created) == 1
    assert created[0].parent == root
    assert created[0].name.endswith("--Fix-login")
    assert not any(path.suffix == ".md" for path in created[0].iterdir())


def test_canceling_the_name_creates_nothing(
    runtime: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.prompt.KDialogPrompt.ask",
        lambda self, text: None,
    )
    with pytest.raises(SystemExit) as caught:
        main(["-s"])
    assert caught.value.code == 0
    root = runtime["root"]
    editor = runtime["editor"]
    assert isinstance(root, Path)
    assert isinstance(editor, FakeEditor)
    assert list(root.iterdir()) == []
    assert editor.commands == []


def test_resume_without_sessions_exits(
    runtime: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "neovim_harness.prompt.KDialogPrompt.error",
        lambda self, text: errors.append(text),
    )
    with pytest.raises(SystemExit) as caught:
        main(["-r"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == "No sessions to resume.\n"
    assert errors == ["No sessions to resume."]
    editor = runtime["editor"]
    assert isinstance(editor, FakeEditor)
    assert editor.commands == []


def test_resume_opens_the_chosen_document(runtime: dict[str, object]) -> None:
    root = runtime["root"]
    editor = runtime["editor"]
    clipboard = runtime["clipboard"]
    assert isinstance(root, Path)
    assert isinstance(editor, FakeEditor)
    assert isinstance(clipboard, FakeClipboard)
    session = root / "doc-261005141803"
    session.mkdir()
    document = session / "doc-261005141803.md"
    document.write_text("body\n", encoding="utf-8")

    def pick(catalog_path: Path, choice_path: Path) -> int:
        editor.picks.append((catalog_path, choice_path))
        choice_path.write_text(str(session), encoding="utf-8")
        return 0

    editor.pick = pick
    main(["-r"])
    assert editor.commands == [["+start"]]
    assert editor.files == [document]
    assert editor.directories == [session]
    assert clipboard.writes == []
    assert clipboard.reads == []


def test_module_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("neovim_harness.cli.collect_failures", lambda: [])
    monkeypatch.setattr(sys, "argv", ["neovim.harness", "--check-environment"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("neovim_harness", run_name="__main__")
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"{SUCCESS_TEXT}\n"

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from neovim_harness.modes import NamedSession, ResumeSession
from neovim_harness.repository import GitInitError
from neovim_harness.sessions import SessionStore, _rename_exclusive
from neovim_harness.workspace import (
    NamedSessionSource,
    ResumeSessionSource,
    SessionLifecycle,
    Workspace,
)

_WHEN = datetime(2026, 10, 5, 14, 18, 3)


class _Prompt:
    def __init__(self, answers: list[str | None]) -> None:
        self.answers = answers
        self.texts: list[str] = []

    def ask(self, text: str) -> str | None:
        self.texts.append(text)
        return self.answers.pop(0)


class _Dialogs:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, text: str) -> None:
        self.errors.append(text)


class _Git:
    def __init__(self) -> None:
        self.directories: list[Path] = []

    def init(self, directory: Path) -> None:
        self.directories.append(directory)
        (directory / ".git").mkdir()


class _Picker:
    def __init__(self, choose: str | None, code: int = 0) -> None:
        self.choose = choose
        self.code = code
        self.catalogs: list[list[dict[str, str]]] = []

    def pick(self, catalog_path: Path, choice_path: Path) -> int:
        self.catalogs.append(json.loads(catalog_path.read_text(encoding="utf-8")))
        if self.choose is not None:
            choice_path.write_text(self.choose, encoding="utf-8")
        return self.code


def test_named_session_retries_then_creates_an_empty_repository(tmp_path: Path) -> None:
    prompt = _Prompt(["///", "Fix login"])
    git = _Git()
    workspace = NamedSessionSource(
        SessionStore(tmp_path, clock=lambda: _WHEN),
        prompt,
        git,
    ).open()
    assert prompt.texts[1].startswith("That name cannot be used")
    assert workspace.file is None
    assert workspace.publish_clipboard is False
    assert workspace.directory.name == "doc-261005141803--Fix-login"
    assert git.directories == [workspace.directory]
    assert list(workspace.directory.iterdir()) == [workspace.directory / ".git"]


def test_failed_git_init_removes_an_empty_session_and_exits(tmp_path: Path) -> None:
    message = "The git command is not on PATH. Is it installed and in your PATH?"
    dialogs = _Dialogs()

    class Fail:
        def init(self, directory: Path) -> None:
            raise GitInitError(message)

    with pytest.raises(SystemExit) as caught:
        NamedSessionSource(
            SessionStore(tmp_path, clock=lambda: _WHEN),
            _Prompt(["Fix login"]),
            Fail(),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == [message]
    assert list(tmp_path.iterdir()) == []


def test_failed_git_init_removes_a_directory_that_contains_only_git(
    tmp_path: Path,
) -> None:
    message = "Failed to create the git repository.\nfatal: cannot create repository"
    dialogs = _Dialogs()

    class Fail:
        def init(self, directory: Path) -> None:
            git_dir = directory / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            raise GitInitError(message)

    with pytest.raises(SystemExit) as caught:
        NamedSessionSource(
            SessionStore(tmp_path, clock=lambda: _WHEN),
            _Prompt(["Fix login"]),
            Fail(),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == [message]
    assert list(tmp_path.iterdir()) == []


def test_failed_git_init_keeps_a_directory_that_holds_another_file(
    tmp_path: Path,
) -> None:
    message = "Failed to create the git repository: boom"
    dialogs = _Dialogs()

    class Fail:
        def init(self, directory: Path) -> None:
            (directory / ".git").mkdir()
            (directory / "notes.txt").write_text("keep", encoding="utf-8")
            raise GitInitError(message)

    with pytest.raises(SystemExit) as caught:
        NamedSessionSource(
            SessionStore(tmp_path, clock=lambda: _WHEN),
            _Prompt(["Fix login"]),
            Fail(),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == [message]
    kept = tmp_path / "doc-261005141803--Fix-login"
    assert (kept / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert (kept / ".git").is_dir()


def test_cancel_raises_before_a_directory_exists(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        NamedSessionSource(
            SessionStore(tmp_path, clock=lambda: _WHEN),
            _Prompt([None]),
            _Git(),
        ).open()
    assert caught.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_resume_cancel_and_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    (directory / "note.txt").write_text("hello\n", encoding="utf-8")
    store = SessionStore(tmp_path)
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as cancelled:
        ResumeSessionSource(store, _Picker(None, code=0), dialogs).open()
    assert cancelled.value.code == 0
    assert dialogs.errors == []
    with pytest.raises(SystemExit) as failed:
        ResumeSessionSource(store, _Picker(None, code=1), dialogs).open()
    assert failed.value.code == 1
    assert dialogs.errors == ["Could not open the session list."]
    assert "Could not open the session list." in caplog.text


def test_resume_rejects_a_path_outside_the_root(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    (directory / "note.txt").write_text("hello\n", encoding="utf-8")
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as caught:
        ResumeSessionSource(
            SessionStore(tmp_path),
            _Picker(str(tmp_path)),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == ["Selected session is not in the session root."]
    assert "Selected session is not in the session root." in caplog.text


def test_resume_rejects_a_name_that_is_not_a_session(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    (directory / "note.txt").write_text("hello\n", encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as caught:
        ResumeSessionSource(
            SessionStore(tmp_path),
            _Picker(str(notes)),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == ["Selected session is not in the session root."]
    assert "Selected session is not in the session root." in caplog.text


def test_resume_reports_a_missing_session_directory(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    (directory / "note.txt").write_text("hello\n", encoding="utf-8")
    missing = tmp_path / "doc-261005141804--Fix-login"
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as caught:
        ResumeSessionSource(
            SessionStore(tmp_path),
            _Picker(str(missing)),
            dialogs,
        ).open()
    assert caught.value.code == 1
    assert dialogs.errors == ["Selected session no longer exists."]
    assert "Selected session no longer exists." in caplog.text
    assert not missing.exists()


def test_resume_opens_a_project_directory_without_a_document(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803--Fix-login"
    directory.mkdir()
    (directory / "note.txt").write_text("hello\n", encoding="utf-8")
    picker = _Picker(str(directory))
    workspace = ResumeSessionSource(SessionStore(tmp_path), picker).open()
    assert workspace.directory == directory
    assert workspace.file is None
    assert workspace.publish_clipboard is False
    assert picker.catalogs[0][0]["label"] == directory.name
    assert "note.txt" in picker.catalogs[0][0]["preview"]


def test_resume_ignores_a_symlink_document(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    target = tmp_path / "elsewhere.md"
    target.write_text("secret\n", encoding="utf-8")
    link = directory / f"{directory.name}.md"
    link.symlink_to(target)
    workspace = ResumeSessionSource(
        SessionStore(tmp_path),
        _Picker(str(directory)),
    ).open()
    assert workspace.directory == directory
    assert workspace.file is None


def test_resume_opens_the_clipboard_document(tmp_path: Path) -> None:
    directory = tmp_path / "doc-261005141803"
    directory.mkdir()
    document = directory / "doc-261005141803.md"
    document.write_text("body\n", encoding="utf-8")
    workspace = ResumeSessionSource(SessionStore(tmp_path), _Picker(str(directory))).open()
    assert workspace.file == document


def test_relocate_initializes_git_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    git = _Git()
    dialogs = _Dialogs()
    lifecycle = SessionLifecycle(store, git, dialogs)
    workspace = Workspace(document.parent, document, True, tmp_path / "missing-request")
    assert lifecycle.relocate(workspace) is None

    request = tmp_path / "requests" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    moved = lifecycle.relocate(
        Workspace(document.parent, document, True, request)
    )
    assert moved is not None
    assert moved.publish_clipboard is False
    assert moved.directory.name == "doc-261005141803--Later"
    assert moved.file == moved.directory / f"{moved.directory.name}.md"
    assert moved.file is not None
    assert moved.file.read_text(encoding="utf-8") == ""
    assert not (moved.directory / document.name).exists()
    assert git.directories == [moved.directory]
    assert not request.parent.exists()

    again_request = tmp_path / "again" / "rename-request"
    again_request.parent.mkdir()
    again_request.write_text("Later", encoding="utf-8")
    second = lifecycle.relocate(
        Workspace(moved.directory, moved.file, False, again_request)
    )
    assert second is not None
    assert second.directory == moved.directory
    assert second.file == moved.file
    assert git.directories == [moved.directory]

    caplog.set_level(logging.ERROR)
    bad = tmp_path / "bad" / "rename-request"
    bad.parent.mkdir()
    bad.write_bytes(b"\xff")
    reopened = lifecycle.relocate(Workspace(second.directory, second.file, False, bad))
    assert reopened is not None
    assert reopened.directory == second.directory
    assert "That session name cannot be used in a folder name." in caplog.text
    assert dialogs.errors == ["That session name cannot be used in a folder name."]


def test_relocate_keeps_the_directory_when_the_document_name_is_taken(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    blocker = document.parent / "doc-261005141803--Later.md"
    blocker.write_text("other", encoding="utf-8")
    request = tmp_path / "req" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    dialogs = _Dialogs()
    git = _Git()
    caplog.set_level(logging.ERROR)
    reopened = SessionLifecycle(store, git, dialogs).relocate(
        Workspace(document.parent, document, True, request)
    )
    assert reopened is not None
    assert reopened.directory == document.parent
    assert reopened.file == document
    assert reopened.publish_clipboard is True
    assert document.is_file()
    assert blocker.read_text(encoding="utf-8") == "other"
    assert not (tmp_path / "doc-261005141803--Later").exists()
    assert git.directories == []
    message = f"This session folder cannot be renamed. {blocker} is in the way."
    assert dialogs.errors == [message]
    assert message in caplog.text


def test_relocate_opens_the_renamed_session_when_git_init_fails(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    message = "Failed to create the git repository.\nfatal: cannot create repository"
    request = tmp_path / "req" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    dialogs = _Dialogs()

    class Fail:
        def init(self, directory: Path) -> None:
            raise GitInitError(message)

    moved = SessionLifecycle(store, Fail(), dialogs).relocate(
        Workspace(document.parent, document, True, request)
    )
    assert moved is not None
    assert moved.directory == tmp_path / "doc-261005141803--Later"
    assert moved.file == moved.directory / "doc-261005141803--Later.md"
    assert moved.file is not None
    assert moved.file.is_file()
    assert moved.publish_clipboard is False
    assert dialogs.errors == [message]
    assert not (moved.directory / ".git").exists()


def test_relocate_rejects_a_directory_outside_the_store(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path / "sessions", clock=lambda: _WHEN)
    outside = tmp_path / "elsewhere" / "doc-261005141803"
    outside.parent.mkdir()
    outside.mkdir()
    request = tmp_path / "rename-parent" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    caplog.set_level(logging.ERROR)
    dialogs = _Dialogs()
    reopened = SessionLifecycle(store, _Git(), dialogs).relocate(
        Workspace(outside, None, False, request)
    )
    assert reopened is not None
    assert reopened.directory == outside
    assert "This session folder cannot be renamed." in caplog.text
    assert dialogs.errors == ["This session folder cannot be renamed."]


def test_resume_without_sessions_notifies_and_exits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dialogs = _Dialogs()
    with pytest.raises(SystemExit) as caught:
        ResumeSessionSource(SessionStore(tmp_path), _Picker(None), dialogs).open()
    assert caught.value.code == 0
    assert capsys.readouterr().out == "No sessions to resume.\n"
    assert dialogs.errors == ["No sessions to resume."]


def test_resume_through_a_symlinked_root_renames(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    store = SessionStore(link, clock=lambda: _WHEN)
    document = store.create()
    dialogs = _Dialogs()

    class Picker:
        def pick(self, catalog_path: Path, choice_path: Path) -> int:
            choice_path.write_text(str(document.parent.resolve()), encoding="utf-8")
            return 0

    workspace = ResumeSessionSource(store, Picker(), dialogs).open()
    assert workspace.directory == link / document.parent.name
    assert workspace.file == workspace.directory / f"{workspace.directory.name}.md"
    request = tmp_path / "rename" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    moved = SessionLifecycle(store, _Git(), dialogs).relocate(
        Workspace(workspace.directory, workspace.file, False, request)
    )
    assert moved is not None
    assert moved.directory == link / "doc-261005141803--Later"
    assert moved.file == moved.directory / "doc-261005141803--Later.md"
    assert moved.file is not None
    assert moved.file.is_file()
    assert dialogs.errors == []


def test_failed_document_rename_reopens_the_original_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    request = tmp_path / "req" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    real_exclusive = _rename_exclusive

    def boom(source: Path, target: Path) -> None:
        if source.suffix == ".md":
            raise OSError("cannot rename document")
        real_exclusive(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", boom)
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    reopened = SessionLifecycle(store, _Git(), dialogs).relocate(
        Workspace(document.parent, document, True, request)
    )
    assert reopened is not None
    assert reopened.directory == document.parent
    assert reopened.file == document
    assert reopened.publish_clipboard is True
    assert document.is_file()
    assert not (tmp_path / "doc-261005141803--Later").exists()
    assert dialogs.errors == ["This session folder cannot be renamed."]
    assert "cannot rename document" in caplog.text


def test_relocate_renames_the_old_document_when_the_folder_already_matches(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    directory = document.parent
    target = tmp_path / f"{directory.name}--Later"
    directory.rename(target)
    carried = target / document.name
    assert carried.is_file()
    request = tmp_path / "rename" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    dialogs = _Dialogs()
    moved = SessionLifecycle(store, _Git(), dialogs).relocate(
        Workspace(target, carried, True, request)
    )
    assert moved is not None
    assert moved.directory == target
    assert moved.file == target / f"{target.name}.md"
    assert moved.file is not None
    assert moved.file.is_file()
    assert moved.file.read_text(encoding="utf-8") == ""
    assert not carried.exists()
    assert dialogs.errors == []


def test_failed_restore_reopens_the_directory_that_still_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    document.write_text("kept", encoding="utf-8")
    request = tmp_path / "req" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    real_exclusive = _rename_exclusive

    def fail_restore(source: Path, target: Path) -> None:
        if source.suffix == ".md":
            raise OSError("cannot rename document")
        if target == document.parent and source != document.parent:
            raise OSError("cannot restore")
        real_exclusive(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", fail_restore)
    dialogs = _Dialogs()
    git = _Git()
    caplog.set_level(logging.ERROR)
    reopened = SessionLifecycle(store, git, dialogs).relocate(
        Workspace(document.parent, document, True, request)
    )
    surviving = tmp_path / "doc-261005141803--Later"
    assert reopened is not None
    assert reopened.directory == surviving
    assert surviving.is_dir()
    assert not document.parent.exists()
    assert reopened.file == surviving / document.name
    assert reopened.file is not None
    assert reopened.file.read_text(encoding="utf-8") == "kept"
    assert reopened.publish_clipboard is True
    assert git.directories == []
    message = (
        f"This session folder is already at {surviving}. "
        "The previous name could not be restored."
    )
    assert dialogs.errors == [message]
    assert message in caplog.text
    assert "cannot rename document" in caplog.text
    assert "Could not restore the session folder: cannot restore" in caplog.text


def test_rename_oserror_reopens_the_same_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SessionStore(tmp_path, clock=lambda: _WHEN)
    document = store.create()
    request = tmp_path / "req" / "rename-request"
    request.parent.mkdir()
    request.write_text("Later", encoding="utf-8")
    real_exclusive = _rename_exclusive

    def boom(source: Path, target: Path) -> None:
        if source == document.parent:
            raise OSError("read-only file system")
        real_exclusive(source, target)

    monkeypatch.setattr("neovim_harness.sessions._rename_exclusive", boom)
    dialogs = _Dialogs()
    caplog.set_level(logging.ERROR)
    reopened = SessionLifecycle(store, _Git(), dialogs).relocate(
        Workspace(document.parent, document, True, request)
    )
    assert reopened is not None
    assert reopened.directory == document.parent
    assert reopened.file == document
    assert document.is_file()
    assert "This session folder cannot be renamed." in caplog.text
    assert "read-only file system" in caplog.text
    assert dialogs.errors == ["This session folder cannot be renamed."]


def test_session_modes_do_not_touch_a_clipboard() -> None:
    class Clipboard:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, data: str, mimetype: str = "text/plain") -> None:
            self.writes.append(data)

    clipboard = Clipboard()
    for mode in (NamedSession(), ResumeSession()):
        mode.prepare(None, clipboard, None)  # type: ignore[arg-type]
        assert mode.ex_commands() == ["+start"]
        mode.publish("text", clipboard, None)  # type: ignore[arg-type]
    assert clipboard.writes == []

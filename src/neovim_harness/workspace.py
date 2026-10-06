"""Open a workspace and move it after the editor asks for a new name."""

from __future__ import annotations

import json
import logging
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from neovim_harness.prompt import KDialogPrompt, NamePrompt, ShowsError
from neovim_harness.repository import GitInitError, InitializesGit
from neovim_harness.sessions import (
    SessionStore,
    is_session_directory,
    session_document,
    slugify,
)

logger = logging.getLogger(__name__)

_NAME_PROMPT = "Name this session. It is stored with the date so you can find it later."
_NAME_RETRY = "That name cannot be used in a folder name. Use letters, numbers, and spaces."
_NO_SESSIONS = "No sessions to resume."
_INVALID_NAME = "That session name cannot be used in a folder name."
_CANNOT_RENAME = "This session folder cannot be renamed."
_OUTSIDE_ROOT = "Selected session is not in the session root."
_SESSION_GONE = "Selected session no longer exists."
_LIST_FAILED = "Could not open the session list."


@dataclass(frozen=True)
class Workspace:
    directory: Path
    file: Path | None
    publish_clipboard: bool
    rename_request: Path


class OpensWorkspace(Protocol):
    def open(self) -> Workspace: ...


class RelocatesWorkspace(Protocol):
    def relocate(self, workspace: Workspace) -> Workspace | None: ...


class SessionPicker(Protocol):
    def pick(self, catalog_path: Path, choice_path: Path) -> int: ...


class ClipboardSessionSource:
    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    def open(self) -> Workspace:
        path = self._sessions.create()
        return Workspace(
            directory=path.parent,
            file=path,
            publish_clipboard=True,
            rename_request=new_rename_request(),
        )


class NamedSessionSource:
    def __init__(
        self,
        sessions: SessionStore,
        prompt: NamePrompt,
        git: InitializesGit,
        notifier: ShowsError | None = None,
    ) -> None:
        self._sessions = sessions
        self._prompt = prompt
        self._git = git
        self._notifier = notifier if notifier is not None else KDialogPrompt()

    def open(self) -> Workspace:
        text = _NAME_PROMPT
        while True:
            raw = self._prompt.ask(text)
            if raw is None:
                raise SystemExit(0)
            slug = slugify(raw)
            if slug is not None:
                break
            text = _NAME_RETRY
        directory = self._sessions.create_named(slug)
        try:
            self._git.init(directory)
        except GitInitError as exc:
            self._notifier.error(str(exc))
            _discard_failed_session(directory)
            raise SystemExit(1) from exc
        return Workspace(
            directory=directory,
            file=None,
            publish_clipboard=False,
            rename_request=new_rename_request(),
        )


class ResumeSessionSource:
    def __init__(
        self,
        sessions: SessionStore,
        picker: SessionPicker,
        notifier: ShowsError | None = None,
    ) -> None:
        self._sessions = sessions
        self._picker = picker
        self._notifier = notifier if notifier is not None else KDialogPrompt()

    def open(self) -> Workspace:
        entries = self._sessions.catalog()
        if not entries:
            print(_NO_SESSIONS)
            self._notifier.error(_NO_SESSIONS)
            raise SystemExit(0)
        with tempfile.TemporaryDirectory(prefix="neovim-harness-") as temporary:
            root = Path(temporary)
            catalog_path = root / "catalog.json"
            choice_path = root / "choice"
            payload = [entry.as_json() for entry in entries]
            catalog_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            code = self._picker.pick(catalog_path, choice_path)
            if not choice_path.is_file():
                if code != 0:
                    self._reject(_LIST_FAILED)
                raise SystemExit(0)
            raw = choice_path.read_text(encoding="utf-8")
        directory = self._selected(raw)
        return Workspace(
            directory=directory,
            file=session_document(directory),
            publish_clipboard=False,
            rename_request=new_rename_request(),
        )

    def _selected(self, raw: str) -> Path:
        selected = Path(raw.strip()).resolve()
        root = self._sessions.root.resolve()
        in_root = selected.parent == root
        session_name = is_session_directory(selected.name)
        if in_root and session_name and not selected.is_dir():
            self._reject(_SESSION_GONE)
        if not in_root or not session_name:
            self._reject(_OUTSIDE_ROOT)
        return self._sessions.root / selected.name

    def _reject(self, message: str) -> None:
        logger.error(message)
        self._notifier.error(message)
        raise SystemExit(1)


class SessionLifecycle:
    def __init__(
        self,
        sessions: SessionStore,
        git: InitializesGit,
        notifier: ShowsError | None = None,
    ) -> None:
        self._sessions = sessions
        self._git = git
        self._notifier = notifier if notifier is not None else KDialogPrompt()

    def relocate(self, workspace: Workspace) -> Workspace | None:
        raw = consume_rename_request(workspace.rename_request)
        if raw is None:
            return None
        slug = slugify(raw)
        if slug is None:
            self._report(_INVALID_NAME)
            return _reopen(workspace)
        had_document = session_document(workspace.directory) is not None
        document_stem = workspace.file.stem if workspace.file is not None else None
        try:
            directory = self._sessions.rename(
                workspace.directory,
                slug,
                document_stem=document_stem,
            )
        except (ValueError, OSError) as exc:
            surviving = _surviving_directory(exc)
            if surviving is not None:
                message = _unrestored_directory_message(surviving)
                logger.error("%s: %s", message, exc)
                self._notifier.error(message)
                return _reopen(workspace, surviving)
            if isinstance(exc, ValueError):
                self._report(_rename_failure_message(exc))
            else:
                logger.error("%s: %s", _CANNOT_RENAME, exc)
                self._notifier.error(_CANNOT_RENAME)
            return _reopen(workspace)
        if not (directory / ".git").exists():
            try:
                self._git.init(directory)
            except GitInitError as exc:
                self._notifier.error(str(exc))
        return Workspace(
            directory=directory,
            file=_file_after_rename(workspace, directory, had_document),
            publish_clipboard=False,
            rename_request=new_rename_request(),
        )

    def _report(self, message: str) -> None:
        logger.error(message)
        self._notifier.error(message)


def _rename_failure_message(exc: ValueError) -> str:
    blocking = exc.args[0] if exc.args else None
    if isinstance(blocking, Path):
        return f"{_CANNOT_RENAME} {blocking} is in the way."
    return _CANNOT_RENAME


def _unrestored_directory_message(directory: Path) -> str:
    return (
        f"This session folder is already at {directory}. "
        "The previous name could not be restored."
    )


def _discard_failed_session(directory: Path) -> None:
    """Remove a new session that is empty or contains only ``.git``."""
    try:
        children = list(directory.iterdir())
    except OSError:
        return
    if any(child.name != ".git" for child in children):
        return
    for child in children:
        try:
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
        except OSError:
            return
    try:
        directory.rmdir()
    except OSError:
        return


def new_rename_request() -> Path:
    root = Path(tempfile.mkdtemp(prefix="neovim-harness-"))
    return root / "rename-request"


def discard_rename_request(path: Path) -> None:
    """Remove the request directory when the editor does not return."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        path.parent.rmdir()
    except OSError:
        pass


def consume_rename_request(path: Path) -> str | None:
    text: str | None = None
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = ""
        path.unlink(missing_ok=True)
    parent = path.parent
    try:
        parent.rmdir()
    except OSError:
        pass
    return text


def _file_after_rename(
    workspace: Workspace,
    directory: Path,
    had_document: bool,
) -> Path | None:
    new_document = directory / f"{directory.name}.md"
    if workspace.file is None:
        old_document = directory / f"{workspace.directory.name}.md"
        if (
            had_document
            and workspace.directory.name != directory.name
            and _regular_file(new_document)
            and not old_document.exists()
        ):
            return new_document
        return None
    carried = directory / workspace.file.name
    if _regular_file(new_document) and carried != new_document and not carried.exists():
        return new_document
    if _regular_file(carried):
        return carried
    return None


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _surviving_directory(exc: BaseException) -> Path | None:
    directory = getattr(exc, "surviving_directory", None)
    if isinstance(directory, Path):
        return directory
    return None


def _reopen(workspace: Workspace, directory: Path | None = None) -> Workspace:
    chosen = workspace.directory if directory is None else directory
    file = workspace.file
    if file is not None and chosen != workspace.directory:
        file = chosen / file.name
    return Workspace(
        directory=chosen,
        file=file,
        publish_clipboard=workspace.publish_clipboard,
        rename_request=new_rename_request(),
    )

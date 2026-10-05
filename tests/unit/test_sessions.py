from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from neovim_harness.sessions import SessionStore, sessions_root

_WHEN = datetime(2026, 10, 5, 14, 18, 3)
_STAMP = "doc-261005141803"


def _store(root: Path) -> SessionStore:
    return SessionStore(root, clock=lambda: _WHEN)


def test_session_name_and_mode(tmp_path: Path) -> None:
    previous = os.umask(0)
    try:
        path = _store(tmp_path).create()
    finally:
        os.umask(previous)
    assert path.parent.name == _STAMP
    assert path.name == f"{_STAMP}.md"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text(encoding="utf-8") == ""


def test_collision_suffix_keeps_the_existing_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create()
    (first.parent / "keep").write_text("stay", encoding="utf-8")
    second = store.create()
    third = store.create()
    assert second.parent.name == f"{_STAMP}-2"
    assert second.name == f"{_STAMP}-2.md"
    assert third.parent.name == f"{_STAMP}-3"
    assert third.name == f"{_STAMP}-3.md"
    assert (first.parent / "keep").read_text(encoding="utf-8") == "stay"
    assert first.exists()


def test_mkdir_race_uses_the_next_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_mkdir = Path.mkdir
    raised = False

    def flaky_mkdir(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        nonlocal raised
        if self.name == _STAMP and not raised:
            raised = True
            raise FileExistsError(self)
        real_mkdir(self, mode, parents, exist_ok)

    monkeypatch.setattr(Path, "mkdir", flaky_mkdir)
    path = _store(tmp_path).create()
    assert raised
    assert not (tmp_path / _STAMP).exists()
    assert path.parent.name == f"{_STAMP}-2"
    assert path.name == f"{_STAMP}-2.md"
    assert path.stat().st_mode & 0o777 == 0o600


def test_collision_fills_the_first_free_suffix(tmp_path: Path) -> None:
    (tmp_path / _STAMP).mkdir()
    (tmp_path / f"{_STAMP}-3").mkdir()
    path = _store(tmp_path).create()
    assert path.parent.name == f"{_STAMP}-2"
    assert path.name == f"{_STAMP}-2.md"


def test_relative_override_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert sessions_root({"NEOVIM_HARNESS_SESSIONS": "relative/path"}, home) == (
        home / ".neovim.harness" / "sessions"
    )
    assert sessions_root({"NEOVIM_HARNESS_SESSIONS": ""}, home) == (
        home / ".neovim.harness" / "sessions"
    )
    assert sessions_root({}, home) == home / ".neovim.harness" / "sessions"


def test_absolute_override_is_the_session_root(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    home = tmp_path / "home"
    root = sessions_root({"NEOVIM_HARNESS_SESSIONS": str(custom)}, home)
    path = SessionStore(root, clock=lambda: _WHEN).create()
    assert root == custom
    assert path.parent.parent == custom
    assert not home.exists()

"""Keep the unit suite off the real clipboard, Neovide, and home sessions."""

from __future__ import annotations

from pathlib import Path

import pytest

from neovim_harness.sessions import SessionStore

_ORIGINAL_CREATE = SessionStore.create
_HOME_SESSIONS = Path.home() / ".neovim.harness"


def _refuse_subprocess(*args: object, **kwargs: object) -> None:
    command = args[0] if args else kwargs.get("args")
    raise AssertionError(f"subprocess refused in unit tests: {command}")


def _guarded_create(self: SessionStore) -> Path:
    try:
        self._root.resolve().relative_to(_HOME_SESSIONS.resolve())
    except ValueError:
        return _ORIGINAL_CREATE(self)
    raise AssertionError(f"refusing to create a session under {_HOME_SESSIONS}")


@pytest.fixture(autouse=True)
def _keep_unit_tests_off_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    for target in (
        "neovim_harness.editor.subprocess.run",
        "neovim_harness.clipboard.subprocess.run",
        "neovim_harness.convert.subprocess.run",
    ):
        monkeypatch.setattr(target, _refuse_subprocess)
    monkeypatch.setattr(SessionStore, "create", _guarded_create)

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from neovim_harness.editor import NeovideEditor


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "doc-1" / "doc-1.md"
    path.parent.mkdir()
    path.write_text("x", encoding="utf-8")
    return path


def test_argv_cwd_and_detached_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 7)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.INFO)
    path = _file(tmp_path)
    NeovideEditor().open(path, ["+start", "+colorscheme retrobox"])
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert seen["args"] == (
        [
            "neovide",
            "--no-fork",
            str(path),
            "--",
            "+start",
            "+colorscheme retrobox",
        ],
    )
    assert kwargs["cwd"] == path.parent
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["check"] is False
    assert f"Opening editor: {path}" in caplog.text


def test_no_ex_commands_still_pass_the_separator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    path = _file(tmp_path)
    NeovideEditor().open(path, [])
    assert seen["command"] == ["neovide", "--no-fork", str(path), "--"]


def test_missing_executable_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("neovide")

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as caught:
        NeovideEditor().open(_file(tmp_path), ["+start"])
    assert caught.value.code == 1
    assert (
        "Neovide executable not found. Is it installed and in your PATH?"
        in caplog.text
    )


def test_other_launch_failure_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no display")

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as caught:
        NeovideEditor().open(_file(tmp_path), [])
    assert caught.value.code == 1
    assert "Failed to launch editor: no display" in caplog.text

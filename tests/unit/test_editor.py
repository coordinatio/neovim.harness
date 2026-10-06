from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from neovim_harness.editor import NeovideEditor


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "doc-1" / "doc-1.md"
    path.parent.mkdir()
    path.write_text("x", encoding="utf-8")
    return path


def _editor(tmp_path: Path) -> tuple[NeovideEditor, Path, Path]:
    rename = tmp_path / "rename.lua"
    resume = tmp_path / "resume.lua"
    return NeovideEditor(rename, resume), rename, resume


def _dofile(path: Path) -> str:
    return f"lua dofile([=[{path}]=])"


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
    editor, rename, _resume = _editor(tmp_path)
    request = tmp_path / "rename-request"
    editor.open(path.parent, ["+start", "+colorscheme retrobox"], path, request)
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
            "-c",
            _dofile(rename),
        ],
    )
    assert kwargs["cwd"] == path.parent
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["check"] is False
    environ = kwargs["env"]
    assert isinstance(environ, dict)
    assert environ["NEOVIM_HARNESS_RENAME_FILE"] == str(request)
    assert f"Opening editor: {path}" in caplog.text


def test_directory_launch_omits_the_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    directory = tmp_path / "doc-1"
    directory.mkdir()
    editor, rename, _resume = _editor(tmp_path)
    editor.open(directory, ["+start"], None, tmp_path / "rename-request")
    assert seen["command"] == [
        "neovide",
        "--no-fork",
        "--",
        "+start",
        "-c",
        _dofile(rename),
    ]
    assert seen["cwd"] == directory


def test_lua_path_that_contains_a_long_bracket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    rename = tmp_path / "a]=]b.lua"
    editor = NeovideEditor(rename, tmp_path / "resume.lua")
    directory = tmp_path / "session"
    directory.mkdir()
    editor.open(directory, [], None, tmp_path / "rename-request")
    command = seen["command"]
    assert isinstance(command, list)
    assert command[-1] == f"lua dofile([==[{rename}]==])"


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
    editor, rename, _resume = _editor(tmp_path)
    editor.open(path.parent, [], path, tmp_path / "rename-request")
    assert seen["command"] == [
        "neovide",
        "--no-fork",
        str(path),
        "--",
        "-c",
        _dofile(rename),
    ]


def test_picker_uses_the_resume_script_and_returns_the_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 3)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.INFO)
    editor, _rename, resume = _editor(tmp_path)
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    catalog.write_text("[]", encoding="utf-8")
    assert editor.pick(catalog, choice) == 3
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert seen["command"] == [
        "neovide",
        "--no-fork",
        "--",
        "--noplugin",
        "-i",
        "NONE",
        "-u",
        "NONE",
        "-c",
        _dofile(resume),
    ]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    environ = kwargs["env"]
    assert isinstance(environ, dict)
    assert environ["NEOVIM_HARNESS_CATALOG"] == str(catalog)
    assert environ["NEOVIM_HARNESS_CHOICE"] == str(choice)
    assert "Opening session list." in caplog.text


_GIT_LOCATION = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


def test_launches_drop_a_foreign_git_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    foreign = tmp_path / "elsewhere"
    monkeypatch.setenv("GIT_DIR", str(foreign))
    for key in _GIT_LOCATION[1:]:
        monkeypatch.setenv(key, "foreign")
    monkeypatch.setenv("KEPT_FOR_THE_EDITOR", "yes")
    envs: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    editor, _rename, _resume = _editor(tmp_path)
    directory = tmp_path / "doc-1"
    directory.mkdir()
    request = tmp_path / "rename-request"
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    editor.open(directory, ["+start"], None, request)
    editor.pick(catalog, choice)
    assert len(envs) == 2
    for environ in envs:
        assert isinstance(environ, dict)
        for key in _GIT_LOCATION:
            assert key not in environ
        assert environ["KEPT_FOR_THE_EDITOR"] == "yes"
    assert envs[0]["NEOVIM_HARNESS_RENAME_FILE"] == str(request)
    assert envs[1]["NEOVIM_HARNESS_CATALOG"] == str(catalog)
    assert envs[1]["NEOVIM_HARNESS_CHOICE"] == str(choice)
    assert os.environ["GIT_DIR"] == str(foreign)


def test_launches_drop_neovide_directory_and_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEOVIDE_CHDIR", "/elsewhere")
    monkeypatch.setenv("NEOVIDE_SERVER", "/tmp/nvim.sock")
    monkeypatch.setenv("KEPT_FOR_THE_EDITOR", "yes")
    envs: list[object] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    editor, _rename, _resume = _editor(tmp_path)
    directory = tmp_path / "doc-1"
    directory.mkdir()
    request = tmp_path / "rename-request"
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    editor.open(directory, ["+start"], None, request)
    editor.pick(catalog, choice)
    assert len(envs) == 2
    for environ in envs:
        assert isinstance(environ, dict)
        assert "NEOVIDE_CHDIR" not in environ
        assert "NEOVIDE_SERVER" not in environ
        assert environ["KEPT_FOR_THE_EDITOR"] == "yes"
    assert os.environ["NEOVIDE_CHDIR"] == "/elsewhere"
    assert os.environ["NEOVIDE_SERVER"] == "/tmp/nvim.sock"


def test_missing_executable_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("neovide")

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    path = _file(tmp_path)
    editor, _rename, _resume = _editor(tmp_path)
    with pytest.raises(SystemExit) as caught:
        editor.open(path.parent, ["+start"], path, tmp_path / "rename-request")
    assert caught.value.code == 1
    assert (
        "Neovide executable not found. Is it installed and in your PATH?"
        in caplog.text
    )


def test_missing_session_directory_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("neovide")

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    editor, _rename, _resume = _editor(tmp_path)
    missing = tmp_path / "doc-missing"
    with pytest.raises(SystemExit) as caught:
        editor.open(missing, ["+start"], None, tmp_path / "rename-request")
    assert caught.value.code == 1
    assert "The session directory is gone." in caplog.text
    assert "Neovide executable not found" not in caplog.text


def test_other_launch_failure_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no display")

    monkeypatch.setattr("neovim_harness.editor.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    path = _file(tmp_path)
    editor, _rename, _resume = _editor(tmp_path)
    with pytest.raises(SystemExit) as caught:
        editor.open(path.parent, [], path, tmp_path / "rename-request")
    assert caught.value.code == 1
    assert "Failed to launch editor: no display" in caplog.text

from __future__ import annotations

import locale
import logging
import os
import subprocess
from pathlib import Path

import pytest

from neovim_harness.repository import GitInitError, GitRepository


def test_init_uses_main_and_detached_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        (tmp_path / ".git").mkdir()
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.DEBUG, logger="neovim_harness.repository")
    GitRepository().init(tmp_path)
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert seen["command"] == ["git", "init", "-b", "main"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.PIPE
    assert kwargs["text"] is True
    assert kwargs["errors"] == "replace"
    assert kwargs["check"] is False
    assert f"Initializing git repository in {tmp_path}" in caplog.text


_GIT_LOCATION = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


def test_init_drops_a_foreign_git_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    monkeypatch.setenv("GIT_DIR", str(foreign))
    for key in _GIT_LOCATION[1:]:
        monkeypatch.setenv(key, "foreign")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Kept")
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["env"] = kwargs.get("env")
        (tmp_path / ".git").mkdir()
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    GitRepository().init(tmp_path)
    env = seen["env"]
    assert isinstance(env, dict)
    for key in _GIT_LOCATION:
        assert key not in env
    assert env["GIT_AUTHOR_NAME"] == "Kept"
    assert os.environ["GIT_DIR"] == str(foreign)
    assert (tmp_path / ".git").is_dir()
    assert not (foreign / ".git").exists()


def test_init_without_a_git_directory_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 0, stderr="")

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(GitInitError) as caught:
        GitRepository().init(tmp_path)
    assert str(caught.value) == "Failed to create the git repository."
    assert str(caught.value) in caplog.text
    assert not (tmp_path / ".git").exists()


def test_missing_git_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(GitInitError) as caught:
        GitRepository().init(tmp_path)
    assert str(caught.value) == (
        "The git command is not on PATH. Is it installed and in your PATH?"
    )
    assert str(caught.value) in caplog.text


def test_git_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0],
            1,
            stderr="fatal: cannot create repository\n",
        )

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(GitInitError) as caught:
        GitRepository().init(tmp_path)
    assert str(caught.value) == (
        "Failed to create the git repository.\nfatal: cannot create repository"
    )
    assert str(caught.value) in caplog.text


def test_init_reports_a_non_utf8_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = b"fatal: \xff"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        encoding = kwargs.get("encoding") or locale.getpreferredencoding(False)
        errors = kwargs.get("errors", "strict")
        assert isinstance(encoding, str)
        assert isinstance(errors, str)
        stderr = raw.decode(encoding, errors)
        return subprocess.CompletedProcess(args[0], 1, stderr=stderr)

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(GitInitError) as caught:
        GitRepository().init(tmp_path)
    detail = raw.decode(locale.getpreferredencoding(False), "replace").rstrip()
    assert str(caught.value) == f"Failed to create the git repository.\n{detail}"
    assert "UnicodeDecodeError" not in str(caught.value)
    assert str(caught.value) in caplog.text


def test_other_git_error_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("neovim_harness.repository.subprocess.run", fake_run)
    caplog.set_level(logging.ERROR)
    with pytest.raises(GitInitError) as caught:
        GitRepository().init(tmp_path)
    assert str(caught.value) == "Failed to create the git repository: boom"
    assert str(caught.value) in caplog.text

from __future__ import annotations

import subprocess

import pytest

from neovim_harness.prompt import KDialogPrompt


def _completed(
    code: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["kdialog"], code, stdout=stdout, stderr=stderr)


def test_input_box_returns_the_text_without_the_trailing_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return _completed(0, "Fix login\n")

    monkeypatch.setattr("neovim_harness.prompt.subprocess.run", fake_run)
    assert KDialogPrompt().ask("Name this session") == "Fix login"
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert seen["command"] == [
        "kdialog",
        "--title",
        "Neovim Harness",
        "--inputbox",
        "Name this session",
    ]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["text"] is True
    assert kwargs["check"] is False


def test_cancel_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.prompt.subprocess.run",
        lambda *args, **kwargs: _completed(1, stderr="closed"),
    )
    caplog.set_level("ERROR")
    assert KDialogPrompt().ask("Name") is None
    assert "Failed to ask for a session name." not in caplog.text


def test_missing_kdialog_exits(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("kdialog")

    monkeypatch.setattr("neovim_harness.prompt.subprocess.run", fake_run)
    caplog.set_level("ERROR")
    with pytest.raises(SystemExit) as caught:
        KDialogPrompt().ask("Name")
    assert caught.value.code == 1
    assert "The kdialog command is not on PATH." in caplog.text


def test_other_dialog_failure_exits(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no display")

    monkeypatch.setattr("neovim_harness.prompt.subprocess.run", fake_run)
    caplog.set_level("ERROR")
    with pytest.raises(SystemExit) as caught:
        KDialogPrompt().ask("Name")
    assert caught.value.code == 1
    assert "Failed to ask for a session name: no display" in caplog.text


def test_unexpected_status_exits(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.prompt.subprocess.run",
        lambda *args, **kwargs: _completed(2, stderr="cannot open display"),
    )
    caplog.set_level("ERROR")
    with pytest.raises(SystemExit) as caught:
        KDialogPrompt().ask("Name")
    assert caught.value.code == 1
    assert "Failed to ask for a session name." in caplog.text
    assert "cannot open display" in caplog.text


def test_error_dialog_uses_kdialog(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return _completed(0)

    monkeypatch.setattr("neovim_harness.prompt.subprocess.run", fake_run)
    KDialogPrompt().error("No sessions to resume.")
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert seen["command"] == [
        "kdialog",
        "--title",
        "Neovim Harness",
        "--error",
        "No sessions to resume.",
    ]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["text"] is True
    assert kwargs["check"] is False


def test_error_dialog_treats_cancel_as_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.prompt.subprocess.run",
        lambda *args, **kwargs: _completed(1, stderr="closed"),
    )
    caplog.set_level("ERROR")
    KDialogPrompt().error("No sessions to resume.")
    assert "Failed to show the error dialog." not in caplog.text


def test_error_dialog_logs_stderr_and_returns(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.prompt.subprocess.run",
        lambda *args, **kwargs: _completed(2, stderr="cannot open display"),
    )
    caplog.set_level("ERROR")
    KDialogPrompt().error("No sessions to resume.")
    assert "Failed to show the error dialog." in caplog.text
    assert "cannot open display" in caplog.text

from __future__ import annotations

import logging
import subprocess

import pytest

from neovim_harness.clipboard import ClipboardError, WaylandClipboard


def test_warns_when_wl_copy_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("neovim_harness.clipboard.shutil.which", lambda command: None)
    caplog.set_level(logging.WARNING)
    WaylandClipboard()
    assert "wl-copy not found. Clipboard operations may fail." in caplog.text


def test_silent_when_wl_copy_is_present(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.clipboard.shutil.which",
        lambda command: "/usr/bin/wl-copy",
    )
    caplog.set_level(logging.WARNING)
    WaylandClipboard()
    assert "wl-copy not found" not in caplog.text


def test_read_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout=b"clipped")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    clipboard = WaylandClipboard()
    assert clipboard.read() == b"clipped"
    assert clipboard.read(mimetype="text/html") == b"clipped"
    plain, html = seen
    assert plain[0][0] == ["wl-paste", "--no-newline"]
    assert html[0][0] == ["wl-paste", "--no-newline", "-t", "text/html"]
    assert plain[1]["capture_output"] is True
    assert "check" not in plain[1]
    assert "check" not in html[1]


def test_write_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    clipboard = WaylandClipboard()
    clipboard.write("héllo", mimetype="text/plain")
    clipboard.write("<p>héllo</p>", mimetype="text/html")
    clipboard.write("again", mimetype="")
    plain, html, empty = seen
    assert plain[0][0] == ["wl-copy", "-t", "text/plain"]
    assert plain[1]["input"] == "héllo".encode("utf-8")
    assert plain[1]["check"] is True
    assert "capture_output" not in plain[1]
    assert html[0][0] == ["wl-copy", "-t", "text/html"]
    assert html[1]["input"] == "<p>héllo</p>".encode("utf-8")
    assert empty[0][0] == ["wl-copy"]


def test_read_keeps_stdout_when_the_mime_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 1, stdout=b"partial", stderr=b"missing")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    assert WaylandClipboard().read(mimetype="text/html") == b"partial"


def test_read_required_requests_the_mime_type(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen["command"] = args[0]
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 0, stdout=b"<p>x</p>", stderr=b"")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    assert WaylandClipboard().read_required("text/html") == b"<p>x</p>"
    assert seen["command"] == ["wl-paste", "--no-newline", "-t", "text/html"]
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["capture_output"] is True
    assert "check" not in kwargs


def test_read_required_reports_a_missing_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=b"No suitable type")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError, match="The clipboard has no text/html content"):
        WaylandClipboard().read_required("text/html")


def test_read_required_reports_a_missing_wl_paste(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("wl-paste")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError, match="The wl-paste command is not on PATH"):
        WaylandClipboard().read_required("text/html")


def test_read_required_rejects_an_empty_mime() -> None:
    with pytest.raises(ClipboardError, match="A clipboard MIME type is required"):
        WaylandClipboard().read_required("")

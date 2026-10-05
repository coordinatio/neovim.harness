from __future__ import annotations

import logging
import subprocess

import pytest

from neovim_harness.clipboard import WaylandClipboard


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

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
    assert "timeout" not in plain[1]
    assert "timeout" not in html[1]
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
    assert plain[1]["timeout"] == 30
    assert html[1]["timeout"] == 30
    assert empty[1]["timeout"] == 30
    assert "capture_output" not in plain[1]
    # wl-copy forks a daemon that owns the selection. It must not inherit our
    # stdout, because vim.system reports completion at EOF, and it must not
    # inherit our process group, because cancelling the helper signals it.
    for options in (plain[1], html[1], empty[1]):
        assert options["stdout"] is subprocess.DEVNULL
        assert options["stderr"] is subprocess.DEVNULL
        assert options["start_new_session"] is True
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
    assert kwargs["timeout"] == 30
    assert "check" not in kwargs


def test_read_required_reports_a_missing_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = (
        b'Clipboard content is not available as requested type "text/html".\n',
        b"Nothing is copied\n",
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        stderr = messages[len(seen)]
        seen.append(stderr)
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=stderr)

    seen: list[bytes] = []
    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    for _ in messages:
        with pytest.raises(ClipboardError) as caught:
            WaylandClipboard().read_required("text/html")
        assert str(caught.value) == "The clipboard has no text/html content."


def test_read_required_reports_a_missing_wl_paste(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("wl-paste")

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError, match="The wl-paste command is not on PATH"):
        WaylandClipboard().read_required("text/html")


def test_read_required_rejects_an_empty_mime() -> None:
    with pytest.raises(ClipboardError, match="A clipboard MIME type is required"):
        WaylandClipboard().read_required("")


def test_read_required_surfaces_other_wl_paste_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = b"Failed to connect to a Wayland server: No such file or directory\n"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=stderr)

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        WaylandClipboard().read_required("text/html")
    assert str(caught.value) == (
        "Failed to connect to a Wayland server: No such file or directory"
    )
    assert "The clipboard has no text/html content." not in str(caught.value)


def test_read_required_reports_an_empty_wl_paste_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderrs: tuple[bytes | str | None, ...] = (b"  \n", None)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        stderr = stderrs[len(seen)]
        seen.append(stderr)
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=stderr)

    seen: list[object] = []
    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    for _ in stderrs:
        with pytest.raises(ClipboardError) as caught:
            WaylandClipboard().read_required("text/html")
        assert str(caught.value) == "wl-paste failed."


def test_read_required_accepts_text_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = (
        'Clipboard content is not available as requested type "text/plain".\n',
        "Failed to connect to a Wayland server: No such file or directory\n",
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        stderr = replies[len(seen)]
        seen.append(stderr)
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=stderr)

    seen: list[str] = []
    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as missing:
        WaylandClipboard().read_required("text/plain")
    assert str(missing.value) == "The clipboard has no text/plain content."
    with pytest.raises(ClipboardError) as failed:
        WaylandClipboard().read_required("text/plain")
    assert str(failed.value) == (
        "Failed to connect to a Wayland server: No such file or directory"
    )


def test_read_does_not_turn_a_timeout_into_an_empty_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        assert "timeout" not in kwargs
        raise subprocess.TimeoutExpired(args[0], None)

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        WaylandClipboard().read(mimetype="text/html")


def test_read_required_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        WaylandClipboard().read_required("text/html")
    assert str(caught.value) == "Timed out waiting for wl-paste."


def test_write_failure_names_the_mime_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    clipboard = WaylandClipboard()
    with pytest.raises(ClipboardError) as html_error:
        clipboard.write("<p>x</p>", mimetype="text/html")
    assert str(html_error.value) == "Could not copy text/html to the clipboard."
    with pytest.raises(ClipboardError) as plain_error:
        clipboard.write("x", mimetype="")
    assert str(plain_error.value) == "Could not copy text to the clipboard."


def test_write_missing_command_is_a_clipboard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(args[0])

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        WaylandClipboard().write("hello", mimetype="text/html")
    assert str(caught.value) == "The wl-copy command is not on PATH."


def test_write_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("neovim_harness.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        WaylandClipboard().write("hello", mimetype="text/html")
    assert str(caught.value) == "Timed out waiting for wl-copy."

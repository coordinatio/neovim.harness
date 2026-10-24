"""Wayland clipboard access through wl-copy and wl-paste."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Protocol

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_SECONDS = 30

_MISSING_TYPE_MARKERS = (
    "Nothing is copied",
    "not available as requested type",
)


class ClipboardError(Exception):
    """A required clipboard read or write failed."""


class Clipboard(Protocol):
    def read(self, mimetype: str = "") -> bytes: ...

    def write(self, data: str, mimetype: str = "text/plain") -> None: ...


class ReadsRequiredMime(Protocol):
    def read_required(self, mimetype: str) -> bytes: ...


def _missing_mimetype(stderr: bytes | str | None) -> bool:
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    elif isinstance(stderr, str):
        text = stderr
    else:
        return False
    return any(marker in text for marker in _MISSING_TYPE_MARKERS)


def _required_read_error(mimetype: str, stderr: bytes | str | None) -> ClipboardError:
    if _missing_mimetype(stderr):
        return ClipboardError(f"The clipboard has no {mimetype} content.")
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace").strip()
    elif isinstance(stderr, str):
        text = stderr.strip()
    else:
        text = ""
    if text:
        return ClipboardError(text)
    return ClipboardError("wl-paste failed.")


class WaylandClipboard:
    def __init__(self) -> None:
        if not shutil.which("wl-copy"):
            logger.warning("wl-copy not found. Clipboard operations may fail.")

    def read(self, mimetype: str = "") -> bytes:
        command = ["wl-paste", "--no-newline"]
        if mimetype:
            command.extend(["-t", mimetype])
        # Editor modes publish whatever this returns. A timeout must not become
        # an empty clipboard, so only the strict helper read is timed.
        result = subprocess.run(
            command,
            capture_output=True,
        )
        return result.stdout

    def read_required(self, mimetype: str) -> bytes:
        if not mimetype:
            raise ClipboardError("A clipboard MIME type is required.")
        command = ["wl-paste", "--no-newline", "-t", mimetype]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise ClipboardError("The wl-paste command is not on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ClipboardError("Timed out waiting for wl-paste.") from exc
        if result.returncode != 0:
            raise _required_read_error(mimetype, result.stderr)
        return result.stdout

    def write(self, data: str, mimetype: str = "text/plain") -> None:
        command = ["wl-copy"]
        if mimetype:
            command.extend(["-t", mimetype])
        try:
            subprocess.run(
                command,
                input=data.encode("utf-8"),
                check=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                # wl-copy forks a daemon that owns the selection. It must not
                # inherit our stdout, because vim.system reports completion at
                # EOF, and it must not inherit our process group, because
                # cancelling the helper signals that whole group and would take
                # the just-copied selection with it.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClipboardError("Timed out waiting for wl-copy.") from exc
        except FileNotFoundError as exc:
            raise ClipboardError("The wl-copy command is not on PATH.") from exc
        except subprocess.CalledProcessError as exc:
            # The daemon's stderr is discarded, so report the mime type instead.
            raise ClipboardError(
                f"Could not copy {mimetype or 'text'} to the clipboard."
            ) from exc

"""Wayland clipboard access through wl-copy and wl-paste."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Protocol

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    """A required clipboard read or write failed."""


class Clipboard(Protocol):
    def read(self, mimetype: str = "") -> bytes: ...

    def write(self, data: str, mimetype: str = "text/plain") -> None: ...


class ReadsRequiredMime(Protocol):
    def read_required(self, mimetype: str) -> bytes: ...


class WaylandClipboard:
    def __init__(self) -> None:
        if not shutil.which("wl-copy"):
            logger.warning("wl-copy not found. Clipboard operations may fail.")

    def read(self, mimetype: str = "") -> bytes:
        command = ["wl-paste", "--no-newline"]
        if mimetype:
            command.extend(["-t", mimetype])
        result = subprocess.run(command, capture_output=True)
        return result.stdout

    def read_required(self, mimetype: str) -> bytes:
        if not mimetype:
            raise ClipboardError("A clipboard MIME type is required.")
        command = ["wl-paste", "--no-newline", "-t", mimetype]
        try:
            result = subprocess.run(command, capture_output=True)
        except FileNotFoundError as exc:
            raise ClipboardError("The wl-paste command is not on PATH.") from exc
        if result.returncode != 0:
            raise ClipboardError(f"The clipboard has no {mimetype} content.")
        return result.stdout

    def write(self, data: str, mimetype: str = "text/plain") -> None:
        command = ["wl-copy"]
        if mimetype:
            command.extend(["-t", mimetype])
        subprocess.run(command, input=data.encode("utf-8"), check=True)

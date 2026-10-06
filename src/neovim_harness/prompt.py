"""Ask for a session title before any directory exists."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Protocol

logger = logging.getLogger(__name__)


class NamePrompt(Protocol):
    def ask(self, text: str) -> str | None: ...


class ShowsError(Protocol):
    def error(self, text: str) -> None: ...


class KDialogPrompt:
    """``kdialog`` dialogs. Cancel is exit 1."""

    def ask(self, text: str) -> str | None:
        """``kdialog --inputbox``. Cancel returns None."""
        command = ["kdialog", "--title", "Neovim Harness", "--inputbox", text]
        try:
            completed = _run(command)
        except FileNotFoundError:
            logger.error(
                "The kdialog command is not on PATH. Is it installed and in your PATH?"
            )
            sys.exit(1)
        except Exception as exc:
            logger.error("Failed to ask for a session name: %s", exc)
            sys.exit(1)
        if completed.returncode == 0:
            return completed.stdout.removesuffix("\n")
        if completed.returncode == 1:
            return None
        logger.error("Failed to ask for a session name.\n%s", _stderr(completed))
        sys.exit(1)

    def error(self, text: str) -> None:
        """``kdialog --error``. Dialog failure does not replace the caller's exit."""
        command = ["kdialog", "--title", "Neovim Harness", "--error", text]
        try:
            completed = _run(command)
        except FileNotFoundError:
            logger.error(
                "The kdialog command is not on PATH. Is it installed and in your PATH?"
            )
            return
        except Exception as exc:
            logger.error("Failed to show the error dialog: %s", exc)
            return
        if completed.returncode in (0, 1):
            return
        logger.error("Failed to show the error dialog.\n%s", _stderr(completed))


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _stderr(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or "").rstrip()

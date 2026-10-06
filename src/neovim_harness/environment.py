"""Requirement checks and the user-facing report. No editor or clipboard work."""

from __future__ import annotations

import importlib
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from neovim_harness.assets import AssetPaths

SUCCESS_TEXT = "Neovim Harness environment check passed."


@dataclass(frozen=True)
class RequirementFailure:
    title: str
    paragraph: str


def collect_failures() -> list[RequirementFailure]:
    checks = (
        check_neovide,
        check_pandoc,
        check_git,
        check_kdialog,
        check_wayland_clipboard,
        check_lxml,
        check_premailer,
        check_cssutils,
        check_wayland_session,
        check_assets,
    )
    failures: list[RequirementFailure] = []
    for check in checks:
        failure = check()
        if failure is not None:
            failures.append(failure)
    return failures


def format_report(failures: Sequence[RequirementFailure]) -> str:
    lines = [
        "Neovim Harness could not find everything it needs.",
        "Change the environment as follows, then run the install again.",
        "",
    ]
    for failure in failures:
        lines.append(failure.title)
        lines.extend(f"  {line}" for line in failure.paragraph.splitlines())
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def check_neovide() -> RequirementFailure | None:
    if shutil.which("neovide") is None:
        return RequirementFailure(
            "neovide",
            "The neovide command is not on PATH.\nInstall the neovide package.",
        )
    return None


def check_pandoc() -> RequirementFailure | None:
    if shutil.which("pandoc") is None:
        return RequirementFailure(
            "pandoc",
            "The pandoc command is not on PATH.\nInstall the pandoc-cli package.",
        )
    return None


def check_git() -> RequirementFailure | None:
    if shutil.which("git") is None:
        return RequirementFailure(
            "git",
            "The git command is not on PATH.\nInstall the git package.",
        )
    return None


def check_kdialog() -> RequirementFailure | None:
    if shutil.which("kdialog") is None:
        return RequirementFailure(
            "kdialog",
            "The kdialog command is not on PATH.\nInstall the kdialog package.",
        )
    return None


def check_wayland_clipboard() -> RequirementFailure | None:
    missing = [
        name for name in ("wl-copy", "wl-paste") if shutil.which(name) is None
    ]
    if not missing:
        return None
    if len(missing) == 1:
        line = f"The {missing[0]} command is not on PATH."
    else:
        line = "The wl-copy and wl-paste commands are not on PATH."
    return RequirementFailure(
        "Wayland clipboard",
        f"{line}\nInstall the wl-clipboard package.",
    )


def check_lxml() -> RequirementFailure | None:
    return _import_failure(
        "lxml",
        "lxml",
        "The lxml module cannot be imported.\nInstall the python-lxml package.",
    )


def check_premailer() -> RequirementFailure | None:
    return _import_failure(
        "premailer",
        "premailer",
        "The premailer module cannot be imported.\n"
        "Install the python-premailer package. It is not in the official repositories.",
    )


def check_cssutils() -> RequirementFailure | None:
    return _import_failure(
        "cssutils",
        "cssutils",
        "The cssutils module cannot be imported.\n"
        "Install the python-cssutils package. It is not in the official repositories.",
    )


def check_wayland_session() -> RequirementFailure | None:
    if os.environ.get("WAYLAND_DISPLAY"):
        return None
    return RequirementFailure(
        "Wayland session",
        "WAYLAND_DISPLAY is not set.\nRun this install from a Wayland session.",
    )


def check_assets() -> RequirementFailure | None:
    try:
        assets = AssetPaths.load()
        readable = (
            _readable(assets.lua_filter)
            and _readable(assets.stylesheet)
            and _readable(assets.rename_lua)
            and _readable(assets.resume_lua)
        )
        if readable:
            return None
    except Exception:
        pass
    return RequirementFailure(
        "Assets",
        "The lua filter, the stylesheet, and the editor scripts could not be read.\n"
        "Reinstall neovim.harness.",
    )


def _import_failure(
    module: str,
    title: str,
    paragraph: str,
) -> RequirementFailure | None:
    try:
        importlib.import_module(module)
    except ImportError:
        return RequirementFailure(title, paragraph)
    return None


def _readable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)

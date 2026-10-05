from __future__ import annotations

import sys
from pathlib import Path

import pytest

from neovim_harness.environment import (
    SUCCESS_TEXT,
    RequirementFailure,
    check_assets,
    check_cssutils,
    check_lxml,
    check_neovide,
    check_pandoc,
    check_premailer,
    check_wayland_clipboard,
    check_wayland_session,
    collect_failures,
    format_report,
)

_NEOVIDE = "The neovide command is not on PATH.\nInstall the neovide package."
_PANDOC = "The pandoc command is not on PATH.\nInstall the pandoc-cli package."
_WL_COPY = "The wl-copy command is not on PATH.\nInstall the wl-clipboard package."
_WL_PASTE = "The wl-paste command is not on PATH.\nInstall the wl-clipboard package."
_WL_BOTH = (
    "The wl-copy and wl-paste commands are not on PATH.\n"
    "Install the wl-clipboard package."
)
_LXML = "The lxml module cannot be imported.\nInstall the python-lxml package."
_PREMAILER = (
    "The premailer module cannot be imported.\n"
    "Install the python-premailer package. It is not in the official repositories."
)
_CSSUTILS = (
    "The cssutils module cannot be imported.\n"
    "Install the python-cssutils package. It is not in the official repositories."
)
_WAYLAND = "WAYLAND_DISPLAY is not set.\nRun this install from a Wayland session."
_ASSETS = (
    "The lua filter and the stylesheet could not be read.\n"
    "Reinstall neovim.harness."
)

_SHAPE = """\
Neovim Harness could not find everything it needs.
Change the environment as follows, then run the install again.

neovide
  The neovide command is not on PATH.
  Install the neovide package.

Wayland session
  WAYLAND_DISPLAY is not set.
  Run this install from a Wayland session.
"""


def test_success_text_is_exact() -> None:
    assert SUCCESS_TEXT == "Neovim Harness environment check passed."


def test_neovide_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("neovim_harness.environment.shutil.which", lambda command: None)
    failure = check_neovide()
    assert failure == RequirementFailure("neovide", _NEOVIDE)


def test_pandoc_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("neovim_harness.environment.shutil.which", lambda command: None)
    failure = check_pandoc()
    assert failure == RequirementFailure("pandoc", _PANDOC)


@pytest.mark.parametrize(
    ("missing", "paragraph"),
    [
        (("wl-copy",), _WL_COPY),
        (("wl-paste",), _WL_PASTE),
        (("wl-copy", "wl-paste"), _WL_BOTH),
    ],
)
def test_wayland_clipboard_names_the_missing_command(
    monkeypatch: pytest.MonkeyPatch,
    missing: tuple[str, ...],
    paragraph: str,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.environment.shutil.which",
        lambda command: None if command in missing else f"/usr/bin/{command}",
    )
    assert check_wayland_clipboard() == RequirementFailure("Wayland clipboard", paragraph)


def test_lxml_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "lxml", None)
    assert check_lxml() == RequirementFailure("lxml", _LXML)


def test_premailer_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "premailer", None)
    assert check_premailer() == RequirementFailure("premailer", _PREMAILER)


def test_cssutils_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cssutils", None)
    assert check_cssutils() == RequirementFailure("cssutils", _CSSUTILS)


@pytest.mark.parametrize("value", [None, ""])
def test_wayland_session_message(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    else:
        monkeypatch.setenv("WAYLAND_DISPLAY", value)
    assert check_wayland_session() == RequirementFailure("Wayland session", _WAYLAND)


def test_assets_message_when_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    css = tmp_path / "github-pandoc.css"
    css.write_text("css", encoding="utf-8")

    class Paths:
        lua_filter = tmp_path / "missing.lua"
        stylesheet = css

    monkeypatch.setattr(
        "neovim_harness.environment.AssetPaths.load",
        classmethod(lambda cls: Paths()),
    )
    assert check_assets() == RequirementFailure("Assets", _ASSETS)


def test_assets_message_when_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(cls: object) -> None:
        raise FileNotFoundError("missing assets")

    monkeypatch.setattr(
        "neovim_harness.environment.AssetPaths.load",
        classmethod(explode),
    )
    assert check_assets() == RequirementFailure("Assets", _ASSETS)


def test_report_shape_for_neovide_and_wayland(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.environment.shutil.which",
        lambda command: None if command == "neovide" else f"/usr/bin/{command}",
    )
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert format_report(collect_failures()) == _SHAPE


def test_report_lists_every_missing_requirement_in_table_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("neovim_harness.environment.shutil.which", lambda command: None)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    for name in ("lxml", "premailer", "cssutils"):
        monkeypatch.setitem(sys.modules, name, None)

    def explode(cls: object) -> None:
        raise FileNotFoundError("missing assets")

    monkeypatch.setattr(
        "neovim_harness.environment.AssetPaths.load",
        classmethod(explode),
    )
    failures = collect_failures()
    assert [failure.title for failure in failures] == [
        "neovide",
        "pandoc",
        "Wayland clipboard",
        "lxml",
        "premailer",
        "cssutils",
        "Wayland session",
        "Assets",
    ]
    assert [failure.paragraph for failure in failures] == [
        _NEOVIDE,
        _PANDOC,
        _WL_BOTH,
        _LXML,
        _PREMAILER,
        _CSSUTILS,
        _WAYLAND,
        _ASSETS,
    ]
    report = format_report(failures)
    assert report.startswith(
        "Neovim Harness could not find everything it needs.\n"
        "Change the environment as follows, then run the install again.\n\n"
        "neovide\n"
    )
    assert "\n\nWayland session\n  WAYLAND_DISPLAY is not set.\n" in report
    assert report.endswith("  Reinstall neovim.harness.\n")


def test_collect_failures_is_empty_when_requirements_are_met(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "neovim_harness.environment.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    lua = tmp_path / "backics.lua"
    css = tmp_path / "github-pandoc.css"
    lua.write_text("lua", encoding="utf-8")
    css.write_text("css", encoding="utf-8")

    class Paths:
        lua_filter = lua
        stylesheet = css

    monkeypatch.setattr(
        "neovim_harness.environment.AssetPaths.load",
        classmethod(lambda cls: Paths()),
    )
    assert collect_failures() == []

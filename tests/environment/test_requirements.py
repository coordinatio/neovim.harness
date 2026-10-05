from __future__ import annotations

import pytest

from neovim_harness.environment import (
    check_assets,
    check_cssutils,
    check_lxml,
    check_neovide,
    check_pandoc,
    check_premailer,
    check_wayland_clipboard,
    check_wayland_session,
)


def _require(failure: object) -> None:
    if failure is not None:
        paragraph = getattr(failure, "paragraph", str(failure))
        pytest.fail(paragraph)


def test_neovide_on_path() -> None:
    _require(check_neovide())


def test_pandoc_on_path() -> None:
    _require(check_pandoc())


def test_wayland_clipboard() -> None:
    _require(check_wayland_clipboard())


def test_python_lxml() -> None:
    _require(check_lxml())


def test_python_premailer() -> None:
    _require(check_premailer())


def test_python_cssutils() -> None:
    _require(check_cssutils())


def test_wayland_session() -> None:
    _require(check_wayland_session())


def test_assets_readable() -> None:
    _require(check_assets())

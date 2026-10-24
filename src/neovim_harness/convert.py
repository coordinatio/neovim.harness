"""HTML to Markdown, and Markdown to styled HTML."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

PANDOC_TIMEOUT_SECONDS = 30

_PANDOC_FAILURES = (
    subprocess.CalledProcessError,
    FileNotFoundError,
    UnicodeDecodeError,
)


class _LazyModule:
    """Call a loader on first attribute access, then read attributes from it."""

    def __init__(self, load: Callable[[], object]) -> None:
        self._load_module = load
        self._module: object | None = None

    def _load(self) -> object:
        if self._module is None:
            self._module = self._load_module()
        return self._module

    def __getattr__(self, name: str) -> object:
        return getattr(self._load(), name)


class _CallsPremailer(Protocol):
    def __call__(self, html: str, remove_classes: bool = False) -> str: ...


class _LazyPremailer:
    """Resolve premailer.transform when Markdown is converted to HTML."""

    def __call__(self, html: str, remove_classes: bool = False) -> str:
        from premailer import transform as premailer_transform

        return premailer_transform(html, remove_classes=remove_classes)


def _import_cssutils() -> object:
    import cssutils

    return cssutils


def _import_lxml_html() -> object:
    from lxml import html

    return html


# Names stay on this module so tests can replace them. Import does not load them.
cssutils = _LazyModule(_import_cssutils)
lxml_html = _LazyModule(_import_lxml_html)
premailer_transform: _CallsPremailer = _LazyPremailer()


def _pandoc_failure_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            return stderr.decode("utf-8", errors="replace")
        if isinstance(stderr, str):
            return stderr
        return ""
    return str(exc)


class ConversionError(Exception):
    """Pandoc could not convert the document."""


def _run_pandoc(
    command: list[str],
    payload: bytes,
    *,
    timeout: float | None,
) -> subprocess.CompletedProcess[bytes]:
    # `timeout=None` waits for Pandoc, which editor modes need so that a slow
    # conversion cannot blank the clipboard.
    return subprocess.run(
        command,
        input=payload,
        capture_output=True,
        check=True,
        timeout=timeout,
    )


class HtmlToMarkdown:
    def __init__(self, lua_filter: Path) -> None:
        self._lua_filter = lua_filter

    def convert(self, html_content: bytes) -> str:
        try:
            return self._convert(html_content, timeout=None)
        except ConversionError as exc:
            logger.error("%s", exc)
            return ""

    def convert_strict(self, html_content: bytes) -> str:
        try:
            return self._convert(html_content, timeout=PANDOC_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Timed out waiting for pandoc.") from exc

    def _convert(self, html_content: bytes, *, timeout: float | None) -> str:
        if not html_content:
            return ""
        command = [
            "pandoc",
            "-f",
            "html",
            "-t",
            "gfm-raw_html",
            "--wrap=none",
            f"--lua-filter={self._lua_filter}",
        ]
        try:
            result = _run_pandoc(command, html_content, timeout=timeout)
            return result.stdout.decode("utf-8")
        except _PANDOC_FAILURES as exc:
            raise ConversionError(
                f"Pandoc html_to_gfm failed: {_pandoc_failure_detail(exc)}"
            ) from exc


class MarkdownToHtml:
    def __init__(self, stylesheet: Path) -> None:
        self._stylesheet = stylesheet

    def convert(self, markdown_content: str) -> str:
        try:
            return self._convert(markdown_content, timeout=None)
        except ConversionError as exc:
            logger.error("%s", exc)
            return ""

    def convert_strict(self, markdown_content: str) -> str:
        try:
            return self._convert(markdown_content, timeout=PANDOC_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Timed out waiting for pandoc.") from exc

    def _convert(self, markdown_content: str, *, timeout: float | None) -> str:
        cssutils.log.setLevel(logging.CRITICAL)
        command = [
            "pandoc",
            "-f",
            "markdown+hard_line_breaks+lists_without_preceding_blankline",
            "-c",
            str(self._stylesheet),
            "--embed-resources",
            "--standalone",
        ]
        try:
            proc = _run_pandoc(
                command,
                markdown_content.encode("utf-8"),
                timeout=timeout,
            )
            raw_html = proc.stdout.decode("utf-8")
        except _PANDOC_FAILURES as exc:
            raise ConversionError(
                f"Pandoc failed: {_pandoc_failure_detail(exc)}"
            ) from exc

        try:
            inlined_html = premailer_transform(raw_html, remove_classes=True)
        except Exception as exc:
            logger.error(f"Premailer failed: {exc}")
            return raw_html

        try:
            tree = lxml_html.fromstring(inlined_html)
            body = tree.find("body")
            if body is not None:
                return "".join(
                    lxml_html.tostring(child, encoding="unicode") for child in body
                )
            return inlined_html
        except Exception as exc:
            logger.error(f"XML parsing failed: {exc}")
            return inlined_html

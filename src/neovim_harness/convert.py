"""HTML to Markdown, and Markdown to styled HTML."""

from __future__ import annotations

import logging
import subprocess
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
    """Import a module on first attribute access. Tests replace attributes on this object."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: object | None = None

    def _load(self) -> object:
        if self._module is None:
            if self._name == "cssutils":
                import cssutils as loaded
            else:
                from lxml import html as loaded
            self._module = loaded
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


# Names stay on this module so tests can replace them. Import does not load them.
cssutils = _LazyModule("cssutils")
lxml_html = _LazyModule("lxml.html")
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


class HtmlToMarkdown:
    def __init__(self, lua_filter: Path) -> None:
        self._lua_filter = lua_filter

    def convert(self, html_content: bytes) -> str:
        try:
            return self.convert_strict(html_content)
        except ConversionError as exc:
            logger.error("%s", exc)
            return ""

    def convert_strict(self, html_content: bytes) -> str:
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
            result = subprocess.run(
                command,
                input=html_content,
                capture_output=True,
                check=True,
                timeout=PANDOC_TIMEOUT_SECONDS,
            )
            return result.stdout.decode("utf-8")
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Timed out waiting for pandoc.") from exc
        except _PANDOC_FAILURES as exc:
            raise ConversionError(
                f"Pandoc html_to_gfm failed: {_pandoc_failure_detail(exc)}"
            ) from exc


class MarkdownToHtml:
    def __init__(self, stylesheet: Path) -> None:
        self._stylesheet = stylesheet

    def convert(self, markdown_content: str) -> str:
        try:
            return self.convert_strict(markdown_content)
        except ConversionError as exc:
            logger.error("%s", exc)
            return ""

    def convert_strict(self, markdown_content: str) -> str:
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
            proc = subprocess.run(
                command,
                input=markdown_content.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=PANDOC_TIMEOUT_SECONDS,
            )
            raw_html = proc.stdout.decode("utf-8")
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Timed out waiting for pandoc.") from exc
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

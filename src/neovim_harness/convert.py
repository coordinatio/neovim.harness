"""HTML to Markdown, and Markdown to styled HTML."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cssutils
from lxml import html as lxml_html
from premailer import transform as premailer_transform

logger = logging.getLogger(__name__)

# premailer uses cssutils, which warns on modern CSS.
cssutils.log.setLevel(logging.CRITICAL)

_PANDOC_FAILURES = (
    subprocess.CalledProcessError,
    FileNotFoundError,
    UnicodeDecodeError,
)


def _pandoc_failure_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            return stderr.decode("utf-8", errors="replace")
        if isinstance(stderr, str):
            return stderr
        return ""
    return str(exc)


class HtmlToMarkdown:
    def __init__(self, lua_filter: Path) -> None:
        self._lua_filter = lua_filter

    def convert(self, html_content: bytes) -> str:
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
            )
            return result.stdout.decode("utf-8")
        except _PANDOC_FAILURES as exc:
            logger.error(f"Pandoc html_to_gfm failed: {_pandoc_failure_detail(exc)}")
            return ""


class MarkdownToHtml:
    def __init__(self, stylesheet: Path) -> None:
        self._stylesheet = stylesheet

    def convert(self, markdown_content: str) -> str:
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
            )
            raw_html = proc.stdout.decode("utf-8")
        except _PANDOC_FAILURES as exc:
            logger.error(f"Pandoc failed: {_pandoc_failure_detail(exc)}")
            return ""

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

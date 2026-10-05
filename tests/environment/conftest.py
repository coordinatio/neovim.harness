"""Reprint environment failures as one Neovim Harness report."""

from __future__ import annotations

from neovim_harness.environment import SUCCESS_TEXT, collect_failures, format_report


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    failed = list(terminalreporter.stats.get("failed", []))
    errors = list(terminalreporter.stats.get("error", []))
    if not failed and not errors:
        if int(exitstatus) == 0:
            terminalreporter.write_line(SUCCESS_TEXT)
        return
    failures = collect_failures()
    if failures:
        terminalreporter.write("\n" + format_report(failures))
        return
    for report in [*failed, *errors]:
        text = getattr(report, "longreprtext", "") or ""
        if text:
            terminalreporter.write_line(text)

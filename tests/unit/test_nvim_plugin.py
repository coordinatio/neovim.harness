from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_headless_neovim_plugin() -> None:
    script = ROOT / "tests" / "nvim" / "harness_spec.lua"
    # Unit tests replace subprocess.run. Popen stays available for this headless Neovim run.
    process = subprocess.Popen(
        ["nvim", "--clean", "--headless", "-i", "NONE", "-l", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError(stdout + stderr)
    assert process.returncode == 0, stdout + stderr

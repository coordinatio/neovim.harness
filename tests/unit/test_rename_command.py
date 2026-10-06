"""Headless Neovim check for :HarnessRename. Neovide is not launched."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_NVIM = shutil.which("nvim")
_RUN = subprocess.run
_RENAME = (
    Path(__file__).resolve().parents[2] / "src" / "neovim_harness" / "data" / "rename.lua"
)


def _run(
    tmp_path: Path,
    body: str,
    rename_file: Path,
    prelude: str = "",
) -> subprocess.CompletedProcess[str]:
    driver = tmp_path / "driver.lua"
    driver.write_text(
        textwrap.dedent(
            f"""
            local notes = {{}}
            vim.notify = function(msg)
              table.insert(notes, tostring(msg))
            end
            vim.ui.input = function(_, on_confirm)
              on_confirm("Later")
            end
            {prelude}
            dofile([=[{_RENAME}]=])
            vim.api.nvim_create_autocmd("VimEnter", {{
              callback = function()
                vim.schedule(function()
                  vim.cmd("HarnessRename")
                  {body}
                end)
              end,
            }})
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["NEOVIM_HARNESS_RENAME_FILE"] = str(rename_file)
    assert _NVIM is not None
    return _RUN(
        [_NVIM, "--headless", "--noplugin", "-u", "NONE", "-i", "NONE", "-c", f"luafile {driver}"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_failed_request_write_stays_open_and_leaves_no_file(tmp_path: Path) -> None:
    request = tmp_path / "rename-request"
    marker = tmp_path / "marker.txt"
    prelude = """
    local real_open = io.open
    io.open = function(path, mode)
      local handle, err = real_open(path, mode)
      if handle == nil then
        return nil, err
      end
      local proxy = {}
      return setmetatable(proxy, {
        __index = function(_, key)
          if key == "write" then
            return function()
              return nil, "disk full"
            end
          end
          local value = handle[key]
          if type(value) == "function" then
            return function(_, ...)
              return value(handle, ...)
            end
          end
          return value
        end,
      })
    end
    """
    completed = _run(
        tmp_path,
        textwrap.dedent(
            f"""
            vim.defer_fn(function()
              vim.fn.writefile(notes, [[{marker}]])
              vim.cmd("qa!")
            end, 50)
            """
        ),
        request,
        prelude=textwrap.dedent(prelude),
    )
    assert completed.returncode == 0, completed.stderr
    assert not request.exists()
    assert "Could not record the session name." in marker.read_text(encoding="utf-8")
    assert "disk full" in marker.read_text(encoding="utf-8")


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_unnamed_modified_buffer_stays_open_without_a_request(tmp_path: Path) -> None:
    request = tmp_path / "rename-request"
    marker = tmp_path / "marker.txt"
    named = tmp_path / "notes.md"
    completed = _run(
        tmp_path,
        textwrap.dedent(
            f"""
            vim.defer_fn(function()
              vim.fn.writefile(notes, [[{marker}]])
              vim.cmd("qa!")
            end, 50)
            """
        ),
        request,
        prelude=textwrap.dedent(
            f"""
            vim.cmd("edit " .. vim.fn.fnameescape([[{named}]]))
            vim.api.nvim_buf_set_lines(0, 0, -1, false, {{ "saved" }})
            vim.cmd("write")
            vim.cmd("enew")
            vim.api.nvim_buf_set_lines(0, 0, -1, false, {{ "draft" }})
            """
        ),
    )
    assert completed.returncode == 0, completed.stderr
    assert not request.exists()
    message = marker.read_text(encoding="utf-8")
    assert "Save unnamed buffers in this session, then run :HarnessRename again." in message
    assert "E141" not in message
    assert "Could not save buffers" not in message
    assert named.read_text(encoding="utf-8") == "saved\n"


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_request_write_records_the_name_and_quits(tmp_path: Path) -> None:
    request = tmp_path / "rename-request"
    completed = _run(tmp_path, "", request)
    assert completed.returncode == 0, completed.stderr
    assert request.read_text(encoding="utf-8") == "Later"

"""Headless Neovim check for the session picker. Neovide is not launched."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from neovim_harness.editor import _lua_dofile

_NVIM = shutil.which("nvim")
_RUN = subprocess.run
_RESUME = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "neovim_harness"
    / "data"
    / "resume.lua"
)


def _picker(driver: Path) -> list[str]:
    assert _NVIM is not None
    return [
        _NVIM,
        "--headless",
        "--noplugin",
        "-i",
        "NONE",
        "-u",
        "NONE",
        "-c",
        _lua_dofile(_RESUME),
        "-c",
        f"luafile {driver}",
    ]


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_picker_writes_the_highlighted_row(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    catalog.write_text(
        json.dumps(
            [
                {
                    "directory": "/sessions/doc-261005141803",
                    "label": "doc-261005141803",
                    "modified": "2026-01-01 00:00",
                    "preview": "first preview",
                },
                {
                    "directory": "/sessions/doc-261005141804--Fix-login",
                    "label": "doc-261005141804--Fix-login",
                    "modified": "2026-01-02 00:00",
                    "preview": "second preview",
                },
                {
                    "directory": "/sessions/doc-261006090000--Fix-login",
                    "label": "doc-261006090000--Fix-login",
                    "modified": "2026-01-02 00:00",
                    "preview": "third preview",
                },
            ]
        ),
        encoding="utf-8",
    )
    driver = tmp_path / "driver.lua"
    driver.write_text(
        """
vim.api.nvim_create_autocmd("VimEnter", {
  callback = function()
    vim.defer_fn(function()
      vim.cmd("stopinsert")
      local list_win
      local preview_win
      local prompt_win
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        local buf = vim.api.nvim_win_get_buf(win)
        local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
        local text = table.concat(lines, "\\n")
        if lines[1] == "doc-261005141803  261005141803  2026-01-01 00:00" and lines[2] == "Fix-login  261005141804  2026-01-02 00:00" and lines[3] == "Fix-login  261006090000  2026-01-02 00:00" and #lines == 3 then
          list_win = win
        elseif string.find(text, "preview", 1, true) then
          preview_win = win
        elseif vim.bo[buf].modifiable then
          prompt_win = win
        end
      end
      if list_win == nil or preview_win == nil or prompt_win == nil then
        vim.cmd("cq 1")
        return
      end
      local prompt_buf = vim.api.nvim_win_get_buf(prompt_win)
      local function shown_lines()
        return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(list_win), 0, -1, false)
      end
      vim.api.nvim_buf_set_lines(prompt_buf, 0, -1, false, { "fix login" })
      vim.api.nvim_exec_autocmds("TextChangedI", { buffer = prompt_buf })
      local shown = shown_lines()
      if shown[1] ~= "Fix-login  261005141804  2026-01-02 00:00" or shown[2] ~= "Fix-login  261006090000  2026-01-02 00:00" or #shown ~= 2 then
        vim.cmd("cq 1")
        return
      end
      vim.api.nvim_buf_set_lines(prompt_buf, 0, -1, false, { "doc-261006" })
      vim.api.nvim_exec_autocmds("TextChangedI", { buffer = prompt_buf })
      shown = shown_lines()
      if shown[1] ~= "Fix-login  261006090000  2026-01-02 00:00" or #shown ~= 1 then
        vim.cmd("cq 1")
        return
      end
      vim.cmd("stopinsert")
      vim.api.nvim_set_current_win(preview_win)
      vim.api.nvim_feedkeys(
        vim.api.nvim_replace_termcodes("<CR>", true, false, true),
        "x",
        false
      )
    end, 50)
  end,
})
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["NEOVIM_HARNESS_CATALOG"] = str(catalog)
    env["NEOVIM_HARNESS_CHOICE"] = str(choice)
    completed = _RUN(
        _picker(driver),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert choice.read_text(encoding="utf-8") == "/sessions/doc-261006090000--Fix-login"


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_picker_collapses_repeated_hyphens(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    catalog.write_text(
        json.dumps(
            [
                {
                    "directory": "/sessions/doc-261007100000--hello-world",
                    "label": "doc-261007100000--hello-world",
                    "modified": "2026-01-03 00:00",
                    "preview": "notes",
                },
                {
                    "directory": "/sessions/doc-261005141803",
                    "label": "doc-261005141803",
                    "modified": "2026-01-01 00:00",
                    "preview": "other",
                },
                {
                    "directory": "/sessions/doc-261006090000--Fix-login",
                    "label": "doc-261006090000--Fix-login",
                    "modified": "2026-01-04 00:00",
                    "preview": "login notes",
                },
            ]
        ),
        encoding="utf-8",
    )
    driver = tmp_path / "driver.lua"
    driver.write_text(
        """
vim.api.nvim_create_autocmd("VimEnter", {
  callback = function()
    vim.defer_fn(function()
      vim.cmd("stopinsert")
      local list_win
      local prompt_win
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        local buf = vim.api.nvim_win_get_buf(win)
        local lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
        if vim.bo[buf].modifiable then
          prompt_win = win
        elseif lines[1] == "hello-world  261007100000  2026-01-03 00:00" then
          list_win = win
        end
      end
      if list_win == nil or prompt_win == nil then
        vim.cmd("cq 1")
        return
      end
      local prompt_buf = vim.api.nvim_win_get_buf(prompt_win)
      local function shown_lines()
        return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(list_win), 0, -1, false)
      end
      local function expect(query, row)
        vim.api.nvim_buf_set_lines(prompt_buf, 0, -1, false, { query })
        vim.api.nvim_exec_autocmds("TextChangedI", { buffer = prompt_buf })
        local shown = shown_lines()
        if shown[1] ~= row or #shown ~= 1 then
          vim.cmd("cq 1")
          return
        end
      end
      expect("hello  world", "hello-world  261007100000  2026-01-03 00:00")
      expect("hello world", "hello-world  261007100000  2026-01-03 00:00")
      expect("261006090000--Fix", "Fix-login  261006090000  2026-01-04 00:00")
      expect("261006090000 fix", "Fix-login  261006090000  2026-01-04 00:00")
      local function expect_every_session(query)
        vim.api.nvim_buf_set_lines(prompt_buf, 0, -1, false, { query })
        vim.api.nvim_exec_autocmds("TextChangedI", { buffer = prompt_buf })
        local shown = shown_lines()
        if #shown ~= 3
          or shown[1] ~= "hello-world  261007100000  2026-01-03 00:00"
          or shown[2] ~= "doc-261005141803  261005141803  2026-01-01 00:00"
          or shown[3] ~= "Fix-login  261006090000  2026-01-04 00:00"
        then
          vim.cmd("cq 1")
          return
        end
      end
      expect_every_session("   ")
      expect_every_session("---")
      expect_every_session(" - ")
      vim.cmd("qa!")
    end, 50)
  end,
})
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["NEOVIM_HARNESS_CATALOG"] = str(catalog)
    env["NEOVIM_HARNESS_CHOICE"] = str(choice)
    completed = _RUN(
        _picker(driver),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert not choice.exists()


@pytest.mark.skipif(_NVIM is None, reason="nvim is not on PATH")
def test_failed_choice_write_stays_open_and_removes_the_file(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    choice = tmp_path / "choice"
    marker = tmp_path / "marker.txt"
    catalog.write_text(
        json.dumps(
            [
                {
                    "directory": "/sessions/doc-261005141803",
                    "label": "doc-261005141803",
                    "modified": "2026-01-01 00:00",
                    "preview": "first preview",
                }
            ]
        ),
        encoding="utf-8",
    )
    driver = tmp_path / "driver.lua"
    driver.write_text(
        f"""
vim.api.nvim_create_autocmd("VimEnter", {{
  callback = function()
    vim.defer_fn(function()
      local notes = {{}}
      vim.notify = function(msg)
        table.insert(notes, tostring(msg))
      end
      local real_open = io.open
      io.open = function(path, mode)
        local handle, err = real_open(path, mode)
        if handle == nil then
          return nil, err
        end
        local proxy = {{}}
        return setmetatable(proxy, {{
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
        }})
      end
      vim.cmd("stopinsert")
      local list_win
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        local buf = vim.api.nvim_win_get_buf(win)
        local lines = vim.api.nvim_buf_get_lines(buf, 0, 1, false)
        if lines[1] == "doc-261005141803  261005141803  2026-01-01 00:00" then
          list_win = win
        end
      end
      if list_win == nil then
        vim.cmd("cq 1")
        return
      end
      vim.api.nvim_set_current_win(list_win)
      vim.api.nvim_feedkeys(
        vim.api.nvim_replace_termcodes("<CR>", true, false, true),
        "x",
        false
      )
      vim.fn.writefile(notes, [[{marker}]])
      vim.cmd("qa!")
    end, 50)
  end,
}})
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["NEOVIM_HARNESS_CATALOG"] = str(catalog)
    env["NEOVIM_HARNESS_CHOICE"] = str(choice)
    completed = _RUN(
        _picker(driver),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert not choice.exists()
    message = marker.read_text(encoding="utf-8")
    assert "Could not save the selection." in message
    assert "disk full" in message

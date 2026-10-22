-- Copy a Markdown selection as HTML, and paste clipboard HTML as Markdown.
-- Pandoc and the Wayland clipboard stay in neovim.harness. This module owns the
-- selection, the mappings, and the asynchronous process.

local M = {}

local BLOCKWISE = "\22"
local MAXCOL = 2147483647

local DEFAULTS = {
  command = "neovim.harness",
  mappings = {
    copy_html = "<leader>mh",
    paste_markdown = "<leader>mp",
  },
}

local config = {
  command = DEFAULTS.command,
  mappings = {
    copy_html = DEFAULTS.mappings.copy_html,
    paste_markdown = DEFAULTS.mappings.paste_markdown,
  },
}

local installed = {
  copy_html = nil,
  paste_markdown = nil,
}

local function fail(message)
  vim.notify(message, vim.log.levels.ERROR)
end

local function visual_mode_now()
  local mode = vim.api.nvim_get_mode().mode
  if mode == "v" or mode == "V" or mode == BLOCKWISE then
    return mode
  end
  return nil
end

local function leave_visual()
  if visual_mode_now() ~= nil then
    vim.cmd("normal! \x1b")
  end
end

local function ordered(first, second)
  if first[2] > second[2] or (first[2] == second[2] and first[3] > second[3]) then
    return second, first
  end
  return first, second
end

-- '< and '> stay unset until visual mode ends, so a mapping reads v and the cursor.
local function current_selection()
  local kind = visual_mode_now()
  local first, last
  if kind ~= nil then
    first = vim.fn.getpos("v")
    last = vim.fn.getpos(".")
  else
    kind = vim.fn.visualmode()
    if kind ~= "v" and kind ~= "V" and kind ~= BLOCKWISE then
      return nil
    end
    first = vim.fn.getpos("'<")
    last = vim.fn.getpos("'>")
    if first[2] == 0 or last[2] == 0 then
      return nil
    end
  end
  local start_pos, end_pos = ordered(first, last)
  return {
    kind = kind,
    buf = vim.api.nvim_get_current_buf(),
    start_row = start_pos[2],
    start_col = start_pos[3],
    end_row = end_pos[2],
    end_col = end_pos[3],
  }
end

local function exclusive_col(line, col)
  if col < 1 or col >= MAXCOL or col > #line then
    return #line
  end
  return col + vim.str_utf_end(line, col)
end

local function selection_text(selection)
  local buf = selection.buf
  if selection.kind == "V" then
    local lines = vim.api.nvim_buf_get_lines(buf, selection.start_row - 1, selection.end_row, true)
    return table.concat(lines, "\n") .. "\n"
  end
  local end_line = vim.api.nvim_buf_get_lines(buf, selection.end_row - 1, selection.end_row, true)[1] or ""
  local finish = exclusive_col(end_line, selection.end_col)
  local parts = vim.api.nvim_buf_get_text(
    buf,
    selection.start_row - 1,
    math.max(selection.start_col - 1, 0),
    selection.end_row - 1,
    finish,
    {}
  )
  return table.concat(parts, "\n")
end

local function paste_region(selection)
  if selection.kind == "V" then
    return {
      kind = "V",
      buf = selection.buf,
      start_row = selection.start_row - 1,
      end_row = selection.end_row,
    }
  end
  local end_line = vim.api.nvim_buf_get_lines(
    selection.buf,
    selection.end_row - 1,
    selection.end_row,
    true
  )[1] or ""
  return {
    kind = "v",
    buf = selection.buf,
    start_row = selection.start_row - 1,
    start_col = math.max(selection.start_col - 1, 0),
    end_row = selection.end_row - 1,
    end_col = exclusive_col(end_line, selection.end_col),
  }
end

local function cursor_region()
  local buf = vim.api.nvim_get_current_buf()
  local cursor = vim.api.nvim_win_get_cursor(0)
  local line = vim.api.nvim_buf_get_lines(buf, cursor[1] - 1, cursor[1], true)[1] or ""
  local insert_col = #line
  if cursor[2] < #line then
    insert_col = exclusive_col(line, cursor[2] + 1)
  end
  return {
    kind = "n",
    buf = buf,
    row = cursor[1] - 1,
    col = insert_col,
  }
end

local function command_targets_visual(opts)
  if opts == nil or opts.range ~= 2 then
    return false
  end
  local kind = vim.fn.visualmode()
  if kind ~= "v" and kind ~= "V" and kind ~= BLOCKWISE then
    return false
  end
  local start_line = vim.fn.line("'<")
  local end_line = vim.fn.line("'>")
  if start_line == 0 or end_line == 0 then
    return false
  end
  local low = math.min(start_line, end_line)
  local high = math.max(start_line, end_line)
  return opts.line1 == low and opts.line2 == high
end

local function process_error(result)
  local message = vim.trim((result and result.stderr) or "")
  if message == "" then
    return config.command .. " failed."
  end
  return message
end

local function split_lines(text)
  return vim.split(text, "\n", { plain = true })
end

local function linewise_replacement(text)
  if text == "" then
    return {}
  end
  local lines = split_lines(text)
  if lines[#lines] == "" then
    table.remove(lines)
  end
  return lines
end

local function insert_markdown(region, text)
  if region.kind == "n" then
    if text == "" then
      return
    end
    vim.api.nvim_buf_set_text(region.buf, region.row, region.col, region.row, region.col, split_lines(text))
    return
  end
  if region.kind == "V" then
    vim.api.nvim_buf_set_lines(
      region.buf,
      region.start_row,
      region.end_row,
      false,
      linewise_replacement(text)
    )
    return
  end
  vim.api.nvim_buf_set_text(
    region.buf,
    region.start_row,
    region.start_col,
    region.end_row,
    region.end_col,
    split_lines(text)
  )
end

local function finish_paste(region, result)
  if type(result) ~= "table" or result.code ~= 0 then
    fail(process_error(result))
    return
  end
  if not vim.api.nvim_buf_is_valid(region.buf) then
    fail("The buffer is no longer valid.")
    return
  end
  if vim.api.nvim_buf_get_changedtick(region.buf) ~= region.tick then
    fail("The buffer changed during conversion. The result was not inserted.")
    return
  end
  local applied, apply_error = pcall(insert_markdown, region, result.stdout or "")
  if not applied then
    fail("Could not insert Markdown: " .. tostring(apply_error))
  end
end

local function start_process(args, stdin, on_result)
  local system_opts = { text = true }
  if stdin ~= nil then
    system_opts.stdin = stdin
  end
  local started = pcall(vim.system, args, system_opts, function(result)
    vim.schedule(function()
      on_result(result)
    end)
  end)
  if not started then
    vim.schedule(function()
      fail(config.command .. " is not available.")
    end)
  end
end

local function refuse_blockwise(selection)
  if selection ~= nil and selection.kind == BLOCKWISE then
    leave_visual()
    fail("Blockwise selection cannot be converted.")
    return true
  end
  return false
end

function M.copy_html()
  local selection = current_selection()
  if selection == nil then
    fail("Select text before copying it as HTML.")
    return
  end
  if refuse_blockwise(selection) then
    return
  end
  local read_ok, text = pcall(selection_text, selection)
  leave_visual()
  if not read_ok then
    fail("Could not read the selection.")
    return
  end
  start_process({ config.command, "--markdown-to-clipboard" }, text, function(result)
    if type(result) ~= "table" or result.code ~= 0 then
      fail(process_error(result))
    end
  end)
end

function M.paste_markdown(opts)
  local selection = nil
  if visual_mode_now() ~= nil or command_targets_visual(opts) then
    selection = current_selection()
  end
  if refuse_blockwise(selection) then
    return
  end
  local region
  if selection ~= nil then
    local captured, value = pcall(paste_region, selection)
    if not captured then
      leave_visual()
      fail("Could not read the selection.")
      return
    end
    region = value
  else
    region = cursor_region()
  end
  leave_visual()
  region.tick = vim.api.nvim_buf_get_changedtick(region.buf)
  start_process({ config.command, "--clipboard-to-markdown" }, nil, function(result)
    finish_paste(region, result)
  end)
end

local function mapping_enabled(lhs)
  return type(lhs) == "string" and lhs ~= ""
end

local function delete_mapping(mode, lhs)
  if not mapping_enabled(lhs) then
    return
  end
  pcall(vim.keymap.del, mode, lhs)
end

local function clear_installed()
  delete_mapping("x", installed.copy_html)
  delete_mapping("n", installed.paste_markdown)
  delete_mapping("x", installed.paste_markdown)
  installed.copy_html = nil
  installed.paste_markdown = nil
end

local function resolve_config(opts)
  opts = opts or {}
  local command = DEFAULTS.command
  if type(opts.command) == "string" and opts.command ~= "" then
    command = opts.command
  end
  local copy_html = DEFAULTS.mappings.copy_html
  local paste_markdown = DEFAULTS.mappings.paste_markdown
  if opts.mappings == false then
    copy_html = false
    paste_markdown = false
  elseif type(opts.mappings) == "table" then
    if opts.mappings.copy_html ~= nil then
      copy_html = opts.mappings.copy_html
    end
    if opts.mappings.paste_markdown ~= nil then
      paste_markdown = opts.mappings.paste_markdown
    end
  end
  return {
    command = command,
    mappings = {
      copy_html = copy_html,
      paste_markdown = paste_markdown,
    },
  }
end

local function set_mapping(mode, lhs, callback, description)
  vim.keymap.set(mode, lhs, callback, { silent = true, desc = description })
end

function M.setup(opts)
  if vim.fn.has("nvim-0.10") ~= 1 then
    fail("neovim_harness requires Neovim 0.10 or newer.")
    return
  end
  config = resolve_config(opts)
  clear_installed()
  vim.api.nvim_create_user_command("HarnessCopyHtml", function(command_opts)
    M.copy_html(command_opts)
  end, {
    range = true,
    force = true,
    desc = "Copy the Markdown selection to the clipboard as HTML",
  })
  vim.api.nvim_create_user_command("HarnessPasteMarkdown", function(command_opts)
    M.paste_markdown(command_opts)
  end, {
    range = true,
    force = true,
    desc = "Paste clipboard HTML as Markdown",
  })
  if mapping_enabled(config.mappings.copy_html) then
    set_mapping("x", config.mappings.copy_html, function()
      M.copy_html()
    end, "Copy the Markdown selection to the clipboard as HTML")
    installed.copy_html = config.mappings.copy_html
  end
  if mapping_enabled(config.mappings.paste_markdown) then
    set_mapping("n", config.mappings.paste_markdown, function()
      M.paste_markdown()
    end, "Paste clipboard HTML as Markdown")
    set_mapping("x", config.mappings.paste_markdown, function()
      M.paste_markdown()
    end, "Paste clipboard HTML as Markdown")
    installed.paste_markdown = config.mappings.paste_markdown
  end
end

return M

-- Copy a Markdown selection as HTML, and paste clipboard HTML as Markdown.
-- Pandoc and the Wayland clipboard stay in neovim.harness. This module owns the
-- selection, the mappings, and the asynchronous process.

local M = {}

local BLOCKWISE = "\22"

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

local generation = 0
local active_job = nil

local EMPTY_MARKDOWN = "The converted Markdown is empty. The selection was left unchanged."

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

-- '< and '> stay unset until visual mode ends, so a mapping reads v and the cursor.
local function selection_bounds()
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
  return {
    kind = kind,
    buf = vim.api.nvim_get_current_buf(),
    first = first,
    last = last,
  }
end

local function visual_line_span()
  local kind = vim.fn.visualmode()
  if kind ~= "v" and kind ~= "V" and kind ~= BLOCKWISE then
    return nil
  end
  local start_line = vim.fn.line("'<")
  local end_line = vim.fn.line("'>")
  if start_line == 0 or end_line == 0 then
    return nil
  end
  return math.min(start_line, end_line), math.max(start_line, end_line)
end

-- :1,1 and :'<,'> both arrive as range 2 on the same lines, so that case keeps
-- the visual selection. A single address is always the whole line.
local function line_range_requested(opts)
  if visual_mode_now() ~= nil then
    return false
  end
  if type(opts) ~= "table" or type(opts.range) ~= "number" or opts.range < 1 then
    return false
  end
  if opts.range == 1 then
    return true
  end
  local low, high = visual_line_span()
  if low == nil then
    return true
  end
  return opts.line1 ~= low or opts.line2 ~= high
end

local function visual_range_matches(opts)
  if visual_mode_now() ~= nil or type(opts) ~= "table" or opts.range ~= 2 then
    return false
  end
  local low, high = visual_line_span()
  if low == nil then
    return false
  end
  return opts.line1 == low and opts.line2 == high
end

local function same_position(one, other)
  return one[2] == other[2] and one[3] == other[3] and one[4] == other[4]
end

local function lower_right(one, other)
  if one[2] > other[2] or (one[2] == other[2] and one[3] > other[3]) then
    return one
  end
  return other
end

-- An exclusive charwise selection that ends in column one of a later row keeps
-- the line break that ends the row before it, as Vim's yank does. getregion()
-- drops that break.
local function exclusive_break(bounds)
  if vim.o.selection ~= "exclusive" or same_position(bounds.first, bounds.last) then
    return false
  end
  local raw = lower_right(bounds.first, bounds.last)
  return raw[3] == 1 and raw[2] > math.min(bounds.first[2], bounds.last[2])
end

local function region_text(bounds)
  local lines = vim.fn.getregion(bounds.first, bounds.last, { type = bounds.kind })
  if type(lines) ~= "table" then
    error("Could not read the selection.")
  end
  local text = table.concat(lines, "\n")
  if bounds.kind == "V" or exclusive_break(bounds) then
    text = text .. "\n"
  end
  return text
end

local function line_text(buf, lnum)
  return vim.api.nvim_buf_get_lines(buf, lnum - 1, lnum, true)[1] or ""
end

-- getregionpos columns are 1-based. With off == 0 the end column is the last
-- included byte. A column past the line is a virtualedit tail or EOL.
local function byte_end(line, pos)
  local col = pos[3]
  if col > #line then
    return #line
  end
  if col < 1 then
    return 0
  end
  if pos[4] ~= 0 or vim.str_utf_start(line, col) < 0 then
    -- The position is inside a character, so the whole character is included.
    local last = col + vim.str_utf_end(line, col)
    if last > #line then
      return #line
    end
    return last
  end
  return col
end

local function byte_start(line, pos)
  local col = pos[3]
  if col > #line then
    return #line
  end
  if col < 1 then
    return 0
  end
  return col - 1
end

-- The position just after the line break that ends row `lnum`, or the end of
-- the buffer when that row is the last one.
local function after_break(buf, lnum)
  local count = vim.api.nvim_buf_line_count(buf)
  if lnum < count then
    return lnum, 0
  end
  return count - 1, #line_text(buf, count)
end

-- A charwise span ends where 'selection' puts it. getregionpos reports the
-- last included byte, which cannot name a position past the last byte, so the
-- raw end position decides whether the line break is part of the span.
local function charwise_end(bounds, end_pos)
  local buf = bounds.buf
  local raw = lower_right(bounds.first, bounds.last)
  local text = line_text(buf, raw[2])
  -- An empty exclusive selection keeps one character, as in Visual mode.
  local empty = same_position(bounds.first, bounds.last)
  if vim.o.selection == "exclusive" and not empty then
    -- The character under the cursor is not included. In column one that
    -- character is the break that ends the previous row.
    local col = raw[3] - 1
    if col > #text then
      col = #text
    end
    if col < 0 then
      col = 0
    end
    return raw[2] - 1, col
  end
  if raw[3] <= #text then
    return end_pos[2] - 1, byte_end(text, end_pos)
  end
  -- Past the last byte, a non-zero end offset is the cursor inside a virtual
  -- cell or inside the last character. Neither covers the line break, and
  -- the last real byte is where the span ends.
  if end_pos[4] ~= 0 then
    return end_pos[2] - 1, byte_end(text, end_pos)
  end
  -- Past the last byte the character under the cursor is the line break.
  if vim.o.selection ~= "old" then
    return after_break(buf, raw[2])
  end
  -- "old" leaves the break out. A non-empty row ends with its last real byte.
  if #text > 0 then
    return raw[2] - 1, #text
  end
  -- On an empty row the position names the last byte of the previous row.
  if raw[2] < 2 then
    return 0, 0
  end
  return raw[2] - 2, #line_text(buf, raw[2] - 1)
end

local function paste_region_from(bounds)
  local segments = vim.fn.getregionpos(bounds.first, bounds.last, {
    type = bounds.kind,
    eol = true,
  })
  if type(segments) ~= "table" or segments[1] == nil then
    error("Could not read the selection.")
  end
  local start_pos = segments[1][1]
  local end_pos = segments[#segments][2]
  if bounds.kind == "V" then
    return {
      kind = "V",
      buf = bounds.buf,
      start_row = start_pos[2] - 1,
      end_row = end_pos[2],
    }
  end
  local start_row = start_pos[2] - 1
  local start_col = byte_start(line_text(bounds.buf, start_pos[2]), start_pos)
  local end_row, end_col = charwise_end(bounds, end_pos)
  if end_row < start_row or (end_row == start_row and end_col < start_col) then
    end_row, end_col = start_row, start_col
  end
  return {
    kind = "v",
    buf = bounds.buf,
    start_row = start_row,
    start_col = start_col,
    end_row = end_row,
    end_col = end_col,
  }
end

local function cursor_region()
  local pos = vim.fn.getpos(".")
  local buf = vim.api.nvim_get_current_buf()
  local line = line_text(buf, pos[2])
  local segments = vim.fn.getregionpos(pos, pos, { type = "v", eol = true })
  local col = #line
  if type(segments) == "table" and segments[1] ~= nil then
    col = byte_end(line, segments[1][2])
  end
  return {
    kind = "n",
    buf = buf,
    row = pos[2] - 1,
    col = col,
  }
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

local function place_cursor(buf, row, col)
  if not vim.api.nvim_buf_is_valid(buf) then
    return
  end
  local function apply()
    local line = vim.api.nvim_buf_get_lines(buf, row - 1, row, true)[1] or ""
    if col > #line then
      col = #line
    end
    if col < 0 then
      col = 0
    end
    vim.api.nvim_win_set_cursor(0, { row, col })
    if col > 0 then
      local saved_whichwrap = vim.o.whichwrap
      vim.o.whichwrap = ""
      local ok, snapped = pcall(function()
        -- `h` inside a grapheme moves to its first byte. `h` on a grapheme
        -- boundary moves to the previous character, so keep the move only
        -- when that character still covers the original column.
        vim.cmd("noautocmd keepjumps normal! h")
        local left = vim.api.nvim_win_get_cursor(0)
        if left[1] ~= row or left[2] >= col then
          return col
        end
        local segs = vim.fn.getregionpos(
          vim.fn.getpos("."),
          vim.fn.getpos("."),
          { type = "v", eol = true }
        )
        if type(segs) ~= "table" or segs[1] == nil or segs[1][2] == nil then
          return col
        end
        local last_byte = segs[1][2][3]
        if type(last_byte) ~= "number" or col > last_byte - 1 then
          return col
        end
        return left[2]
      end)
      vim.o.whichwrap = saved_whichwrap
      if ok and type(snapped) == "number" then
        col = snapped
      end
    end
    vim.api.nvim_win_set_cursor(0, { row, col })
  end
  if vim.api.nvim_get_current_buf() == buf then
    apply()
    return
  end
  for _, win in ipairs(vim.api.nvim_list_wins()) do
    if vim.api.nvim_win_get_buf(win) == buf then
      vim.api.nvim_win_call(win, apply)
      return
    end
  end
end

local function insert_markdown(region, text)
  if region.kind == "n" then
    if text == "" then
      return
    end
    local lines = split_lines(text)
    vim.api.nvim_buf_set_text(region.buf, region.row, region.col, region.row, region.col, lines)
    local first = lines[1] or ""
    -- `p` puts the cursor on the first inserted character when the text spans
    -- lines, and on the last character of the single inserted line otherwise.
    local col = region.col
    if #lines == 1 and #first > 0 then
      col = region.col + (#first - 1) + vim.str_utf_start(first, #first)
    end
    place_cursor(region.buf, region.row + 1, col)
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

local function without_document_terminator(text)
  -- Pandoc ends a document with a newline. A hard break is a backslash or two
  -- spaces at the end of the line that newline closes; that newline stays.
  if text:sub(-1) ~= "\n" then
    return text
  end
  local segment = text:sub(1, -2):match("[^\n]*$") or ""
  if segment:sub(-1) == "\\" or segment:sub(-2) == "  " then
    return text
  end
  return text:sub(1, -2)
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
  local text = without_document_terminator(result.stdout or "")
  if text == "" and region.kind ~= "n" then
    fail(EMPTY_MARKDOWN)
    return
  end
  local applied, apply_error = pcall(insert_markdown, region, text)
  if not applied then
    fail("Could not insert Markdown: " .. tostring(apply_error))
  end
end

local function stop_job(job)
  if type(job) ~= "table" then
    return
  end
  local pid = job.pid
  -- Negating the pid signals its process group. Pid 1 would become -1, and
  -- kill(-1) signals every process this user may signal. Only a pid above 1
  -- is a helper group.
  if type(pid) == "number" and pid > 1 then
    -- The helper is the process-group leader. A negative pid signals the
    -- group, including pandoc and wl-paste/wl-copy. job:kill signals one pid.
    local called, signaled = pcall(vim.uv.kill, -pid, "sigterm")
    if called and signaled ~= nil then
      return
    end
  end
  if type(job.kill) == "function" then
    pcall(job.kill, job, "sigterm")
  end
end

local function supersede()
  generation = generation + 1
  local id = generation
  local job = active_job
  active_job = nil
  stop_job(job)
  return id
end

local function start_process(id, args, stdin, on_result)
  local system_opts = {
    text = true,
    env = { NEOVIM_HARNESS_PROCESS_GROUP = "1" },
  }
  if stdin ~= nil then
    system_opts.stdin = stdin
  end
  local job
  local ok = pcall(function()
    job = vim.system(args, system_opts, function(result)
      vim.schedule(function()
        if id ~= generation then
          return
        end
        if active_job == job then
          active_job = nil
        end
        on_result(result)
      end)
    end)
  end)
  if not ok or job == nil then
    vim.schedule(function()
      if id ~= generation then
        return
      end
      fail(config.command .. " is not available.")
    end)
    return
  end
  if id ~= generation then
    stop_job(job)
    return
  end
  active_job = job
end

local function launch_copy(text)
  -- Empty Markdown becomes empty HTML, which would empty the clipboard.
  if text == "" then
    fail("Select text before copying it as HTML.")
    return
  end
  local id = supersede()
  start_process(id, { config.command, "--markdown-to-clipboard" }, text, function(result)
    if type(result) ~= "table" or result.code ~= 0 then
      fail(process_error(result))
    end
  end)
end

local function launch_paste(region)
  leave_visual()
  local id = supersede()
  region.tick = vim.api.nvim_buf_get_changedtick(region.buf)
  start_process(id, { config.command, "--clipboard-to-markdown" }, nil, function(result)
    finish_paste(region, result)
  end)
end

local function copy_line_range(line1, line2)
  local buf = vim.api.nvim_get_current_buf()
  local ok, text = pcall(function()
    local lines = vim.api.nvim_buf_get_lines(buf, line1 - 1, line2, true)
    if #lines == 0 then
      return ""
    end
    return table.concat(lines, "\n") .. "\n"
  end)
  if not ok then
    fail("Could not read the selection.")
    return
  end
  launch_copy(text)
end

local function copy_visual()
  local bounds = selection_bounds()
  if bounds == nil then
    fail("Select text before copying it as HTML.")
    return
  end
  if bounds.kind == BLOCKWISE then
    leave_visual()
    fail("Blockwise selection cannot be converted.")
    return
  end
  local read_ok, text = pcall(region_text, bounds)
  leave_visual()
  if not read_ok then
    fail("Could not read the selection.")
    return
  end
  launch_copy(text)
end

function M.copy_html(opts)
  if line_range_requested(opts) then
    copy_line_range(opts.line1, opts.line2)
    return
  end
  copy_visual()
end

local function paste_visual()
  local bounds = selection_bounds()
  if bounds == nil then
    leave_visual()
    fail("Could not read the selection.")
    return
  end
  if bounds.kind == BLOCKWISE then
    leave_visual()
    fail("Blockwise selection cannot be converted.")
    return
  end
  local captured, region = pcall(paste_region_from, bounds)
  if not captured then
    leave_visual()
    fail("Could not read the selection.")
    return
  end
  launch_paste(region)
end

function M.paste_markdown(opts)
  if line_range_requested(opts) then
    launch_paste({
      kind = "V",
      buf = vim.api.nvim_get_current_buf(),
      start_row = opts.line1 - 1,
      end_row = opts.line2,
    })
    return
  end
  if visual_mode_now() ~= nil or visual_range_matches(opts) then
    paste_visual()
    return
  end
  launch_paste(cursor_region())
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

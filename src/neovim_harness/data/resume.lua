-- Session picker. This file is Neovim's entire config for that window.

local catalog_path = vim.env.NEOVIM_HARNESS_CATALOG
local choice_path = vim.env.NEOVIM_HARNESS_CHOICE

local entries = {}
local filtered = {}
local query = ""
local index = 1
local prompt_win
local list_win
local preview_win
local prompt_buf
local list_buf
local preview_buf
local applying = false
local settling = false

local function quit()
  vim.cmd("qa!")
end

local function fail(message)
  vim.api.nvim_err_writeln(message)
  vim.cmd("cq 1")
  error(message, 0)
end

local function read_catalog()
  if catalog_path == nil or catalog_path == "" or choice_path == nil or choice_path == "" then
    fail("Session list paths are not set.")
  end
  local handle = io.open(catalog_path, "r")
  if handle == nil then
    fail("Session list could not be read.")
  end
  local text = handle:read("*a")
  handle:close()
  local ok, decoded = pcall(vim.json.decode, text)
  if not ok or type(decoded) ~= "table" then
    fail("Session list could not be read.")
  end
  return decoded
end

local function set_lines(buf, lines)
  if #lines == 0 then
    lines = { "" }
  end
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
end

local function basename(path)
  return (string.match(path or "", "([^/]+)$")) or ""
end

local function session_stamp(name)
  return string.match(name or "", "^doc%-(%d%d%d%d%d%d%d%d%d%d%d%d)")
end

local function session_name(entry)
  local base = basename(entry.directory)
  if session_stamp(base) ~= nil then
    return base
  end
  return entry.label or base
end

local function normalize_filter_text(text)
  local lowered = vim.fn.tolower(text)
  local spaced = lowered:gsub("%s", "-")
  return (spaced:gsub("%-+", "-"))
end

local function apply_filter()
  filtered = {}
  local needle = normalize_filter_text(query)
  if needle:match("^%-+$") then
    needle = ""
  end
  for _, entry in ipairs(entries) do
    local label = normalize_filter_text(session_name(entry))
    if needle == "" or vim.fn.stridx(label, needle) >= 0 then
      table.insert(filtered, entry)
    end
  end
  if index > #filtered then
    index = math.max(#filtered, 1)
  end
  if index < 1 then
    index = 1
  end
end

local function render_preview()
  local entry = filtered[index]
  local text
  if entry == nil then
    text = query == "" and "No sessions." or "No matching sessions."
  else
    text = entry.preview or ""
  end
  set_lines(preview_buf, vim.split(text, "\n", { plain = true }))
end

local function on_list_cursor()
  if settling or list_win == nil or not vim.api.nvim_win_is_valid(list_win) then
    return
  end
  if #filtered == 0 or vim.api.nvim_get_current_win() ~= list_win then
    return
  end
  local row = vim.api.nvim_win_get_cursor(list_win)[1]
  if row < 1 or row > #filtered or row == index then
    return
  end
  index = row
  render_preview()
end

local function recognizable_name(label)
  label = label or ""
  local _, split_at = string.find(label, "--", 1, true)
  if split_at == nil then
    return label
  end
  return string.sub(label, split_at + 1)
end

local function render_row(entry)
  local name = session_name(entry)
  local title = recognizable_name(name)
  local date = session_stamp(name)
  local modified = entry.modified or ""
  if date == nil then
    return title .. "  " .. modified
  end
  return title .. "  " .. date .. "  " .. modified
end

local function render_list()
  local lines = {}
  for _, entry in ipairs(filtered) do
    table.insert(lines, render_row(entry))
  end
  if #lines == 0 then
    lines = { query == "" and "No sessions." or "No matching sessions." }
  end
  settling = true
  set_lines(list_buf, lines)
  if #filtered > 0 and vim.api.nvim_win_is_valid(list_win) then
    vim.api.nvim_win_set_cursor(list_win, { index, 0 })
  end
  settling = false
  render_preview()
end

local function move(delta)
  if #filtered == 0 then
    return
  end
  index = index + delta
  if index < 1 then
    index = 1
  elseif index > #filtered then
    index = #filtered
  end
  render_list()
end

local function notify(message)
  vim.notify(message, vim.log.levels.ERROR)
end

local function write_choice(path, directory)
  local handle, open_error = io.open(path, "w")
  if handle == nil then
    return false, open_error
  end
  local written, write_error = handle:write(directory)
  if written == nil then
    handle:close()
    os.remove(path)
    return false, write_error
  end
  local closed, close_error = handle:close()
  if not closed then
    os.remove(path)
    return false, close_error
  end
  return true
end

local function choose()
  local entry = filtered[index]
  if entry == nil or entry.directory == nil or entry.directory == "" then
    return
  end
  local saved, save_error = write_choice(choice_path, entry.directory)
  if not saved then
    local message = "Could not save the selection."
    if save_error ~= nil and save_error ~= "" then
      message = message .. " " .. tostring(save_error)
    end
    notify(message)
    return
  end
  quit()
end

local function on_prompt_changed()
  if applying then
    return
  end
  local lines = vim.api.nvim_buf_get_lines(prompt_buf, 0, -1, false)
  local text = lines[1] or ""
  if #lines > 1 then
    applying = true
    vim.api.nvim_buf_set_lines(prompt_buf, 0, -1, false, { text })
    applying = false
  end
  if text == query then
    return
  end
  query = text
  index = 1
  apply_filter()
  render_list()
end

local function focus_filter()
  if prompt_win ~= nil and vim.api.nvim_win_is_valid(prompt_win) then
    vim.api.nvim_set_current_win(prompt_win)
    vim.cmd("startinsert!")
  end
end

local function map_shared(buf)
  local options = { buffer = buf, nowait = true, silent = true }
  vim.keymap.set("n", "<CR>", choose, options)
  vim.keymap.set("n", "<Esc>", quit, options)
  vim.keymap.set("n", "q", quit, options)
  vim.keymap.set("n", "j", function()
    move(1)
  end, options)
  vim.keymap.set("n", "k", function()
    move(-1)
  end, options)
  vim.keymap.set("n", "<Down>", function()
    move(1)
  end, options)
  vim.keymap.set("n", "<Up>", function()
    move(-1)
  end, options)
  vim.keymap.set("n", "i", focus_filter, options)
  vim.keymap.set("n", "a", focus_filter, options)
end

local function scratch(buf)
  vim.bo[buf].buftype = "nofile"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].swapfile = false
  vim.bo[buf].modifiable = false
end

local function build()
  pcall(vim.cmd, "colorscheme retrobox")
  vim.opt.number = false
  vim.opt.relativenumber = false
  vim.opt.signcolumn = "no"
  entries = read_catalog()
  apply_filter()

  prompt_buf = vim.api.nvim_create_buf(false, true)
  list_buf = vim.api.nvim_create_buf(false, true)
  preview_buf = vim.api.nvim_create_buf(false, true)
  scratch(prompt_buf)
  scratch(list_buf)
  scratch(preview_buf)
  vim.bo[prompt_buf].modifiable = true

  list_win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(list_win, list_buf)
  vim.cmd("aboveleft 1split")
  prompt_win = vim.api.nvim_get_current_win()
  vim.wo.winfixheight = true
  vim.api.nvim_win_set_buf(prompt_win, prompt_buf)
  vim.api.nvim_set_current_win(list_win)
  vim.cmd("botright vsplit")
  preview_win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(preview_win, preview_buf)

  local columns = vim.o.columns
  local list_width = math.max(20, math.floor(columns * 0.4))
  if list_width < columns - 10 then
    vim.api.nvim_win_set_width(list_win, list_width)
  end

  vim.wo[list_win].cursorline = true
  vim.wo[list_win].wrap = false
  vim.wo[preview_win].wrap = true
  pcall(function()
    vim.wo[list_win].winbar = " Sessions"
    vim.wo[preview_win].winbar = " Preview"
    vim.wo[prompt_win].winbar = " Filter    Enter opens    Esc cancels    arrows move"
  end)

  map_shared(list_buf)
  map_shared(preview_buf)
  local insert_options = { buffer = prompt_buf, nowait = true, silent = true }
  vim.keymap.set("i", "<CR>", choose, insert_options)
  vim.keymap.set("i", "<Esc>", quit, insert_options)
  vim.keymap.set("i", "<C-c>", quit, insert_options)
  vim.keymap.set("i", "<Down>", function()
    move(1)
  end, insert_options)
  vim.keymap.set("i", "<Up>", function()
    move(-1)
  end, insert_options)
  vim.keymap.set("n", "<Esc>", quit, { buffer = prompt_buf, nowait = true, silent = true })

  vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, {
    buffer = prompt_buf,
    callback = on_prompt_changed,
  })
  vim.api.nvim_create_autocmd("CursorMoved", {
    buffer = list_buf,
    callback = on_list_cursor,
  })

  render_list()
  focus_filter()
end

vim.api.nvim_create_autocmd("VimEnter", {
  once = true,
  callback = function()
    vim.schedule(build)
  end,
})

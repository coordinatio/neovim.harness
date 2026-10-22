-- Headless checks for the optional Neovim module. vim.system is mocked.

local script = arg[0]
if type(script) ~= "string" or script == "" then
  io.stderr:write("script path is missing\n")
  os.exit(1)
end

local root = vim.fs.dirname(vim.fs.dirname(vim.fs.dirname(script)))
local plugin = root .. "/share/nvim/site/pack/neovim-harness/start/neovim-harness"
local init_lua = plugin .. "/lua/neovim_harness/init.lua"
if vim.fn.filereadable(init_lua) ~= 1 then
  io.stderr:write("missing plugin: " .. init_lua .. "\n")
  os.exit(1)
end

vim.opt.runtimepath:prepend(plugin)
vim.o.swapfile = false
vim.o.undofile = false
vim.o.writebackup = false
vim.o.hidden = true
vim.g.mapleader = ","

local jobs = {}
local notes = {}
local failures = {}
local original_has = vim.fn.has

vim.notify = function(msg, level)
  table.insert(notes, { message = msg, level = level })
end

local function install_system()
  vim.system = function(cmd, opts, on_exit)
    table.insert(jobs, {
      cmd = vim.deepcopy(cmd),
      stdin = opts and opts.stdin,
      text = opts and opts.text,
      shell = opts and opts.shell,
      on_exit = on_exit,
    })
    return { pid = -1 }
  end
end

install_system()

local mod = require("neovim_harness")

local function pump()
  local done = false
  vim.schedule(function()
    done = true
  end)
  if not vim.wait(1000, function()
    return done
  end) then
    error("timed out waiting for Neovim")
  end
end

local function finish(result)
  local job = jobs[#jobs]
  if job == nil or job.on_exit == nil then
    error("no process was started")
  end
  job.on_exit(result)
  pump()
end

local function begin()
  jobs = {}
  notes = {}
  local mode = vim.api.nvim_get_mode().mode
  if mode == "v" or mode == "V" or mode == "\22" then
    vim.cmd("normal! \x1b")
  end
end

local function test(name, fn)
  begin()
  local ok, err = xpcall(fn, debug.traceback)
  vim.fn.has = original_has
  install_system()
  local restored, restore_error = pcall(mod.setup)
  if not ok then
    table.insert(failures, name .. "\n" .. tostring(err))
  elseif not restored then
    table.insert(failures, name .. " restore\n" .. tostring(restore_error))
  end
end

local function check(condition, message)
  if not condition then
    error(message, 2)
  end
end

local function same(actual, expected, message)
  if vim.inspect(actual) ~= vim.inspect(expected) then
    error(message .. "\nactual: " .. vim.inspect(actual) .. "\nexpected: " .. vim.inspect(expected), 2)
  end
end

local function buffer(lines)
  local buf = vim.api.nvim_create_buf(true, false)
  vim.api.nvim_set_current_buf(buf)
  local level = vim.bo[buf].undolevels
  vim.bo[buf].undolevels = -1
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].undolevels = level
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  return buf
end

local function text_of(buf)
  return vim.api.nvim_buf_get_lines(buf, 0, -1, false)
end

local function select_chars(row, start_col, end_col)
  vim.api.nvim_win_set_cursor(0, { row, start_col })
  vim.cmd("normal! v")
  if end_col ~= start_col then
    vim.api.nvim_win_set_cursor(0, { row, end_col })
  end
end

local function select_lines(first, last)
  vim.api.nvim_win_set_cursor(0, { first, 0 })
  vim.cmd("normal! V")
  if last ~= first then
    vim.api.nvim_win_set_cursor(0, { last, 0 })
  end
end

local function select_block()
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("normal! \x16")
  vim.api.nvim_win_set_cursor(0, { 2, 1 })
end

local function mapping(mode, lhs)
  return vim.fn.maparg(lhs, mode, false, true)
end

local function press_copy()
  local info = mapping("x", ",mh")
  check(type(info.callback) == "function", "copy mapping is missing")
  info.callback()
end

local function press_paste_visual()
  local info = mapping("x", ",mp")
  check(type(info.callback) == "function", "visual paste mapping is missing")
  info.callback()
end

local function press_paste_normal()
  local info = mapping("n", ",mp")
  check(type(info.callback) == "function", "normal paste mapping is missing")
  info.callback()
end

local function last_job()
  check(#jobs == 1, "expected one process, got " .. tostring(#jobs))
  return jobs[1]
end

test("setup reports an old Neovim and creates nothing", function()
  vim.fn.has = function(feature)
    if feature == "nvim-0.10" then
      return 0
    end
    return original_has(feature)
  end
  mod.setup()
  same(notes, {
    { message = "neovim_harness requires Neovim 0.10 or newer.", level = vim.log.levels.ERROR },
  }, "version error")
  check(vim.fn.exists(":HarnessCopyHtml") == 0, "copy command was created")
  check(vim.fn.exists(":HarnessPasteMarkdown") == 0, "paste command was created")
  check(#jobs == 0, "a process was started")
end)

test("copy without a selection does not start a process", function()
  local buf = buffer({ "abcd" })
  local before = text_of(buf)
  mod.copy_html()
  same(notes, {
    { message = "Select text before copying it as HTML.", level = vim.log.levels.ERROR },
  }, "missing selection")
  check(#jobs == 0, "a process was started")
  same(text_of(buf), before, "buffer changed")
end)

test("setup registers commands and default mappings without touching p", function()
  check(vim.fn.exists(":HarnessCopyHtml") == 2, "copy command")
  check(vim.fn.exists(":HarnessPasteMarkdown") == 2, "paste command")
  check(type(mapping("x", ",mh").callback) == "function", "copy mapping")
  check(type(mapping("n", ",mp").callback) == "function", "normal paste mapping")
  check(type(mapping("x", ",mp").callback) == "function", "visual paste mapping")
  check(mapping("n", "p").lhs == nil, "p was remapped")
  mod.setup()
  check(vim.fn.exists(":HarnessCopyHtml") == 2, "second setup lost the copy command")
  check(type(mapping("x", ",mh").callback) == "function", "second setup lost the copy mapping")
end)

test("false disables a mapping and the commands stay", function()
  mod.setup({ mappings = { copy_html = false } })
  check(mapping("x", ",mh").callback == nil, "copy mapping stayed enabled")
  check(type(mapping("n", ",mp").callback) == "function", "paste mapping was removed")
  check(type(mapping("x", ",mp").callback) == "function", "visual paste mapping was removed")
  check(vim.fn.exists(":HarnessCopyHtml") == 2, "copy command")
  check(vim.fn.exists(":HarnessPasteMarkdown") == 2, "paste command")
  mod.setup({ mappings = false })
  check(mapping("n", ",mp").callback == nil, "paste mapping stayed enabled")
  check(mapping("x", ",mp").callback == nil, "visual paste mapping stayed enabled")
  check(vim.fn.exists(":HarnessCopyHtml") == 2, "commands were removed")
end)

test("a later setup replaces the command and the previous mapping", function()
  mod.setup({
    command = "my-harness",
    mappings = { copy_html = "gch", paste_markdown = false },
  })
  check(mapping("x", ",mh").callback == nil, "old copy mapping stayed")
  check(type(mapping("x", "gch").callback) == "function", "new copy mapping is missing")
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  mapping("x", "gch").callback()
  local job = last_job()
  same(job.cmd, { "my-harness", "--markdown-to-clipboard" }, "custom argv")
  same(job.stdin, "bc", "custom stdin")
  same(text_of(buf), { "abcd" }, "copy changed the buffer")
end)

test("visual copy sends the characterwise selection and leaves the buffer", function()
  local buf = buffer({ "abcd" })
  local tick = vim.api.nvim_buf_get_changedtick(buf)
  select_chars(1, 1, 2)
  press_copy()
  local job = last_job()
  same(job.cmd, { "neovim.harness", "--markdown-to-clipboard" }, "argv")
  same(job.stdin, "bc", "stdin")
  check(job.text == true, "stdin was not passed as text")
  check(job.shell == nil, "the process used a shell")
  check(vim.api.nvim_buf_get_changedtick(buf) == tick, "copy changed the buffer")
  finish({ code = 0, stdout = "", stderr = "" })
  same(text_of(buf), { "abcd" }, "callback changed the buffer")
  check(#notes == 0, "success notified " .. vim.inspect(notes))
end)

test("linewise copy includes the selected lines", function()
  local buf = buffer({ "one", "two", "three" })
  select_lines(1, 2)
  mod.copy_html()
  same(last_job().stdin, "one\ntwo\n", "linewise stdin")
  same(text_of(buf), { "one", "two", "three" }, "buffer changed")
end)

test("characterwise copy keeps a multibyte character whole", function()
  local buf = buffer({ "héllö" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  mod.copy_html()
  same(last_job().stdin, "é", "multibyte stdin")
  same(text_of(buf), { "héllö" }, "buffer changed")
end)

test("characterwise copy can cross lines", function()
  buffer({ "abcd", "efgh" })
  vim.api.nvim_win_set_cursor(0, { 1, 2 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.cmd("normal! \x1b")
  vim.cmd("'<,'>HarnessCopyHtml")
  same(last_job().stdin, "cd\ne", "cross-line stdin")
end)

test("blockwise copy notifies and does not convert", function()
  local buf = buffer({ "abcd", "efgh" })
  select_block()
  press_copy()
  same(notes, {
    { message = "Blockwise selection cannot be converted.", level = vim.log.levels.ERROR },
  }, "blockwise copy")
  check(#jobs == 0, "a process was started")
  same(text_of(buf), { "abcd", "efgh" }, "buffer changed")
  check(vim.api.nvim_get_mode().mode == "n", "still in visual mode")
end)

test("a failed copy notifies and does not change the buffer", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  press_copy()
  finish({ code = 1, stdout = "", stderr = "Pandoc failed: bad markdown\n" })
  same(notes, {
    { message = "Pandoc failed: bad markdown", level = vim.log.levels.ERROR },
  }, "copy failure")
  same(text_of(buf), { "abcd" }, "buffer changed")
end)

test("a missing program notifies and does not change the buffer", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  vim.system = function()
    error("ENOENT: no such file or directory")
  end
  press_copy()
  pump()
  same(notes, {
    { message = "neovim.harness is not available.", level = vim.log.levels.ERROR },
  }, "missing program")
  check(#jobs == 0, "a process was recorded")
  same(text_of(buf), { "abcd" }, "buffer changed")
end)

test("normal paste inserts after the cursor in one undo", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  local job = last_job()
  same(job.cmd, { "neovim.harness", "--clipboard-to-markdown" }, "argv")
  check(job.stdin == nil, "paste passed stdin")
  check(job.text == true, "text mode")
  check(job.shell == nil, "the process used a shell")
  finish({ code = 0, stdout = "X", stderr = "" })
  same(text_of(buf), { "heXllo" }, "normal paste")
  vim.cmd("silent! undo")
  same(text_of(buf), { "hello" }, "undo")
end)

test("normal paste keeps a multiline result in one undo", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("HarnessPasteMarkdown")
  finish({ code = 0, stdout = "X\nY", stderr = "" })
  same(text_of(buf), { "heX", "Yllo" }, "multiline paste")
  vim.cmd("silent! undo")
  same(text_of(buf), { "hello" }, "undo")
end)

test("normal paste ignores an older visual selection", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  vim.cmd("normal! \x1b")
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("HarnessPasteMarkdown")
  finish({ code = 0, stdout = "X", stderr = "" })
  same(text_of(buf), { "aXbcd" }, "old selection was replaced")
end)

test("visual paste replaces the characterwise selection in one undo", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  vim.cmd("normal! \x1b")
  vim.cmd("'<,'>HarnessPasteMarkdown")
  finish({ code = 0, stdout = "XY", stderr = "" })
  same(text_of(buf), { "aXYd" }, "visual replace")
  vim.cmd("silent! undo")
  same(text_of(buf), { "abcd" }, "undo")
end)

test("visual paste replaces a linewise selection in one undo", function()
  local buf = buffer({ "one", "two", "three" })
  select_lines(2, 2)
  press_paste_visual()
  finish({ code = 0, stdout = "A\nB\n", stderr = "" })
  same(text_of(buf), { "one", "A", "B", "three" }, "linewise replace")
  vim.cmd("silent! undo")
  same(text_of(buf), { "one", "two", "three" }, "undo")
end)

test("blockwise paste notifies and a later normal paste still works", function()
  local buf = buffer({ "abcd", "efgh" })
  select_block()
  press_paste_visual()
  same(notes, {
    { message = "Blockwise selection cannot be converted.", level = vim.log.levels.ERROR },
  }, "blockwise paste")
  check(#jobs == 0, "blockwise started a process")
  notes = {}
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("HarnessPasteMarkdown")
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZbcd", "efgh" }, "normal paste after blockwise")
end)

test("a buffer edit during conversion discards the paste", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("HarnessPasteMarkdown")
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, { "hello!" })
  finish({ code = 0, stdout = "X", stderr = "" })
  same(text_of(buf), { "hello!" }, "stale paste was inserted")
  same(notes, {
    {
      message = "The buffer changed during conversion. The result was not inserted.",
      level = vim.log.levels.ERROR,
    },
  }, "changedtick")
end)

test("an invalid buffer notifies and does not insert", function()
  local buf = buffer({ "hello" })
  vim.cmd("HarnessPasteMarkdown")
  vim.api.nvim_buf_delete(buf, { force = true })
  finish({ code = 0, stdout = "X", stderr = "" })
  same(notes, {
    { message = "The buffer is no longer valid.", level = vim.log.levels.ERROR },
  }, "invalid buffer")
end)

test("missing clipboard HTML notifies and does not change the buffer", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  finish({
    code = 1,
    stdout = "ignored",
    stderr = "The clipboard has no text/html content.\n",
  })
  same(text_of(buf), { "hello" }, "buffer changed")
  same(notes, {
    { message = "The clipboard has no text/html content.", level = vim.log.levels.ERROR },
  }, "missing mime")
end)

test("an empty process error uses the command name", function()
  local buf = buffer({ "hello" })
  vim.cmd("HarnessPasteMarkdown")
  finish({ code = 1, stdout = "", stderr = "   " })
  same(text_of(buf), { "hello" }, "buffer changed")
  same(notes, {
    { message = "neovim.harness failed.", level = vim.log.levels.ERROR },
  }, "empty stderr")
end)

if #failures > 0 then
  io.stderr:write(table.concat(failures, "\n\n") .. "\n")
  os.exit(1)
end
os.exit(0)

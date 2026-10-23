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
    local job = {
      cmd = vim.deepcopy(cmd),
      stdin = opts and opts.stdin,
      text = opts and opts.text,
      env = opts and opts.env,
      shell = opts and opts.shell,
      on_exit = on_exit,
      killed = false,
    }
    function job:kill(signal)
      self.killed = true
      self.signal = signal
    end
    table.insert(jobs, job)
    return job
  end
end

install_system()

local mod = require("neovim_harness")
local original_kill = vim.uv.kill

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
  vim.o.selection = "inclusive"
  vim.o.virtualedit = ""
end

local function test(name, fn)
  begin()
  local ok, err = xpcall(fn, debug.traceback)
  vim.fn.has = original_has
  vim.uv.kill = original_kill
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
  same(vim.api.nvim_win_get_cursor(0), { 1, 2 }, "cursor")
  vim.cmd("silent! undo")
  same(text_of(buf), { "hello" }, "undo")
end)

test("normal paste keeps a multiline result in one undo", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("HarnessPasteMarkdown")
  finish({ code = 0, stdout = "X\nY", stderr = "" })
  same(text_of(buf), { "heX", "Yllo" }, "multiline paste")
  same(vim.api.nvim_win_get_cursor(0), { 1, 2 }, "cursor")
  vim.cmd("silent! undo")
  same(text_of(buf), { "hello" }, "undo")
end)

test("a document terminator does not split normal or characterwise paste", function()
  local cases = {
    {
      stdout = "hello\n",
      normal = { "abhellocd" },
      visual = { "ahellocd" },
    },
    {
      stdout = "hello\n\nworld\n",
      normal = { "abhello", "", "worldcd" },
      visual = { "ahello", "", "worldcd" },
    },
    {
      stdout = "hello\\\nworld\n",
      normal = { "abhello\\", "worldcd" },
      visual = { "ahello\\", "worldcd" },
    },
    {
      stdout = "hello  \nworld\n",
      normal = { "abhello  ", "worldcd" },
      visual = { "ahello  ", "worldcd" },
    },
    {
      stdout = "hello  \n",
      normal = { "abhello  ", "cd" },
      visual = { "ahello  ", "cd" },
    },
    {
      stdout = "\\\n",
      normal = { "ab\\", "cd" },
      visual = { "a\\", "cd" },
    },
  }
  for _, case in ipairs(cases) do
    jobs = {}
    notes = {}
    local buf = buffer({ "abcd" })
    vim.api.nvim_win_set_cursor(0, { 1, 1 })
    press_paste_normal()
    finish({ code = 0, stdout = case.stdout, stderr = "" })
    same(text_of(buf), case.normal, "normal " .. vim.inspect(case.stdout))
    check(#notes == 0, "normal notified " .. vim.inspect(notes))

    jobs = {}
    notes = {}
    buf = buffer({ "abcd" })
    select_chars(1, 1, 1)
    press_paste_visual()
    finish({ code = 0, stdout = case.stdout, stderr = "" })
    same(text_of(buf), case.visual, "visual " .. vim.inspect(case.stdout))
    check(#notes == 0, "visual notified " .. vim.inspect(notes))
  end

  jobs = {}
  notes = {}
  local buf = buffer({ "abcd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  local cursor = vim.api.nvim_win_get_cursor(0)
  press_paste_normal()
  finish({ code = 0, stdout = "\n", stderr = "" })
  same(text_of(buf), { "abcd" }, "empty terminator inserted")
  same(vim.api.nvim_win_get_cursor(0), cursor, "empty terminator cursor")
  check(#notes == 0, "empty terminator notified " .. vim.inspect(notes))

  jobs = {}
  notes = {}
  buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  press_paste_visual()
  finish({ code = 0, stdout = "\n", stderr = "" })
  same(text_of(buf), { "abcd" }, "empty terminator deleted the selection")
  same(notes, {
    {
      message = "The converted Markdown is empty. The selection was left unchanged.",
      level = vim.log.levels.ERROR,
    },
  }, "empty terminator")
end)

test("normal paste leaves the cursor where p leaves it", function()
  local emoji = "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}"
  local combining = "e\u{0301}"
  local samples = {
    emoji,
    "Z" .. emoji,
    combining,
    "XYZ\nQ",
    "hello\nworld",
    combining .. "X\nQ",
    "\nXYZ",
    "  \nX",
  }
  for _, text in ipairs(samples) do
    jobs = {}
    notes = {}
    local buf = buffer({ "a." })
    vim.api.nvim_win_set_cursor(0, { 1, 0 })
    press_paste_normal()
    finish({ code = 0, stdout = text, stderr = "" })
    local pasted = text_of(buf)
    local plugin_cursor = vim.api.nvim_win_get_cursor(0)
    check(#notes == 0, "notified " .. vim.inspect(notes))

    local trimmed = text
    buf = buffer({ "a." })
    vim.api.nvim_win_set_cursor(0, { 1, 0 })
    vim.fn.setreg("z", trimmed, "c")
    vim.cmd('normal! "zp')
    same(text_of(buf), pasted, "text " .. text)
    same(vim.api.nvim_win_get_cursor(0), plugin_cursor, "cursor " .. text)
  end
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

test("a selection that reaches a line break replaces that break", function()
  local cases = {
    -- 'selection'=inclusive highlights the break a past-the-end cursor sits on.
    { lines = { "", "a-" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 0 })
      vim.cmd("normal! v")
    end, want = { "Za-" } },
    { lines = { "bb", "", "" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 2, 0 })
      vim.cmd("normal! v")
    end, want = { "bb", "Z" } },
    { lines = { "ab", "" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 1 })
      vim.cmd("normal! v")
      vim.api.nvim_win_set_cursor(0, { 2, 0 })
    end, want = { "aZ" } },
    { lines = { "ab", "", "cd" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 1 })
      vim.cmd("normal! v")
      vim.api.nvim_win_set_cursor(0, { 2, 0 })
    end, want = { "aZcd" } },
    { lines = { "x", "ab", "y" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 2, 0 })
      vim.cmd("normal! v$")
    end, want = { "x", "Zy" } },
  }
  for _, case in ipairs(cases) do
    jobs = {}
    notes = {}
    local buf = buffer(case.lines)
    case.select()
    press_paste_visual()
    finish({ code = 0, stdout = "Z\n", stderr = "" })
    same(text_of(buf), case.want, "paste over " .. vim.inspect(case.lines))
    check(#notes == 0, "notified " .. vim.inspect(notes))
  end
end)

test("an exclusive copy keeps the break its span covers", function()
  vim.o.selection = "exclusive"
  buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  press_copy()
  same(last_job().stdin, "b\n", "exclusive copy")

  jobs = {}
  buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 1 })
  press_copy()
  same(last_job().stdin, "b\nc", "exclusive copy on a longer line")

  jobs = {}
  vim.o.selection = "inclusive"
  buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  press_copy()
  same(last_job().stdin, "b\nc", "inclusive copy")
end)

test("a span that ends inside a character keeps that character", function()
  local emoji = "\u{1F600}"
  local buf = buffer({ "a" .. emoji .. "b8" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 1, 3 })
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZb8" }, "mid-character span")
  check(#notes == 0, "notified " .. vim.inspect(notes))

  -- Every 'selection' mode replaces the whole character for such a position,
  -- because Vim cannot place a cursor inside one.
  for _, mode in ipairs({ "inclusive", "exclusive", "old" }) do
    for _, span in ipairs({ { 1, 1, 1, 2 }, { 1, 2, 1, 1 } }) do
      jobs = {}
      notes = {}
      vim.o.selection = mode
      buf = buffer({ "héllo" })
      vim.api.nvim_win_set_cursor(0, { span[1], span[2] })
      vim.cmd("normal! v")
      vim.api.nvim_win_set_cursor(0, { span[3], span[4] })
      press_paste_visual()
      finish({ code = 0, stdout = "X", stderr = "" })
      same(text_of(buf), { "hXllo" }, mode .. " " .. vim.inspect(span))
      check(#notes == 0, "notified " .. vim.inspect(notes))
    end
  end
end)

test("exclusive and old selections keep the break they leave out", function()
  vim.o.selection = "exclusive"
  local buf = buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZcd" }, "exclusive") -- Vim leaves the first byte of "cd"

  vim.o.selection = "exclusive"
  jobs = {}
  buf = buffer({ "ab", "" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZ" }, "exclusive to an empty last line")

  vim.o.selection = "old"
  jobs = {}
  buf = buffer({ "ab", "" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZ", "" }, "old")
end)

test("select mode reads and replaces the selected region", function()
  local buf = buffer({ "abcdef", "ghijkl" })
  local tick = vim.api.nvim_buf_get_changedtick(buf)
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! gh")
  same(vim.api.nvim_get_mode().mode, "s", "select mode")
  press_copy()
  same(last_job().stdin, "b", "select-mode copy")
  check(vim.api.nvim_buf_get_changedtick(buf) == tick, "copy changed the buffer")
  vim.cmd("silent! normal! \x1b")

  jobs = {}
  notes = {}
  buf = buffer({ "abcdef", "ghijkl" })
  vim.api.nvim_win_set_cursor(0, { 2, 2 })
  vim.cmd("normal! gh")
  press_paste_visual()
  finish({ code = 0, stdout = "ZZ", stderr = "" })
  same(text_of(buf), { "abcdef", "ghZZjkl" }, "select-mode paste")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("copying an empty or blank selection leaves the clipboard alone", function()
  local cases = {
    { lines = { "", "a-" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 0 })
      vim.cmd("normal! v")
    end },
    -- A linewise copy of a blank line is "\n", which becomes empty HTML.
    { lines = { "", "a-" }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 0 })
      vim.cmd("normal! V")
    end },
    { lines = { "   " }, select = function()
      vim.api.nvim_win_set_cursor(0, { 1, 0 })
      vim.cmd("normal! v$")
    end },
  }
  for _, case in ipairs(cases) do
    jobs = {}
    notes = {}
    buffer(case.lines)
    case.select()
    press_copy()
    same(notes, {
      { message = "Select text before copying it as HTML.", level = vim.log.levels.ERROR },
    }, "blank selection " .. vim.inspect(case.lines))
    check(#jobs == 0, "blank selection started a process")
  end
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

test("a grapheme cluster is copied and replaced whole", function()
  local combining = "e\u{0301}"
  local emoji = "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}"
  local buf = buffer({ combining .. "x" })
  vim.cmd("normal! v")
  local highlighted = table.concat(vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = "v" }), "\n")
  same(highlighted, combining, "combining highlight")
  press_copy()
  same(last_job().stdin, combining, "combining copy")
  jobs = {}
  vim.cmd("normal! v")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "Zx" }, "combining paste")

  jobs = {}
  notes = {}
  buf = buffer({ "a" .. emoji .. "b" })
  vim.cmd("normal! lv")
  highlighted = table.concat(vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = "v" }), "\n")
  same(highlighted, emoji, "emoji highlight")
  press_copy()
  same(last_job().stdin, emoji, "emoji copy")
  jobs = {}
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("normal! lv")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZb" }, "emoji paste")
end)

test("exclusive selection stops before the cursor", function()
  vim.o.selection = "exclusive"
  local buf = buffer({ "abcd" })
  vim.cmd("normal! 0vlll")
  local highlighted = table.concat(vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = "v" }), "\n")
  same(highlighted, "abc", "exclusive highlight")
  press_copy()
  same(last_job().stdin, "abc", "exclusive copy")
  jobs = {}
  notes = {}
  vim.cmd("normal! 0vlll")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "Zd" }, "exclusive paste")
end)

test("virtualedit columns are copied and the buffer keeps real bytes", function()
  vim.o.virtualedit = "all"
  local buf = buffer({ "ab" })
  vim.cmd("normal! 0lv")
  vim.cmd("normal! 5l")
  local highlighted = table.concat(vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = "v" }), "\n")
  same(highlighted, "b" .. string.rep(" ", 5), "virtual highlight")
  press_copy()
  same(last_job().stdin, highlighted, "virtual copy")
  jobs = {}
  vim.cmd("normal! 0lv")
  vim.cmd("normal! 5l")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZ" }, "virtual paste")
end)

test("a virtualedit cell after the line end stops at the real text", function()
  vim.o.virtualedit = "all"
  local buf = buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.cmd("normal! l")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZ", "cd" }, "virtual cell paste")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("a virtualedit empty line stops at the real text", function()
  vim.o.virtualedit = "all"
  local buf = buffer({ "", "a-" })
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.cmd("normal! v")
  press_paste_visual()
  finish({ code = 0, stdout = "Z\n", stderr = "" })
  same(text_of(buf), { "Z", "a-" }, "virtual empty line paste")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("an old selection from a virtualedit position keeps the span", function()
  vim.o.virtualedit = "all"
  vim.o.selection = "old"
  local buf = buffer({ "abcd" })
  vim.api.nvim_win_set_cursor(0, { 1, 4 })
  vim.cmd("normal! v")
  vim.cmd("normal! 0")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "Z" }, "old virtual span paste")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("an old selection past the line end stops at the last byte", function()
  vim.o.virtualedit = "onemore"
  vim.o.selection = "old"
  local buf = buffer({ "ab", "cd" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.cmd("normal! v")
  vim.cmd("normal! l")
  press_paste_visual()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZ", "cd" }, "old onemore paste")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("a single address copies that line", function()
  buffer({ "abcd", "efgh" })
  select_chars(1, 1, 2)
  vim.cmd("normal! \x1b")
  vim.cmd("2HarnessCopyHtml")
  same(last_job().stdin, "efgh\n", "other line")
  jobs = {}
  select_chars(2, 0, 1)
  vim.cmd("normal! \x1b")
  vim.cmd("2HarnessCopyHtml")
  same(last_job().stdin, "efgh\n", "same line")
end)

test("a paste range on other lines replaces those lines", function()
  local buf = buffer({ "abcd", "efgh", "ijkl" })
  select_chars(1, 1, 2)
  vim.cmd("normal! \x1b")
  vim.cmd("2,3HarnessPasteMarkdown")
  finish({ code = 0, stdout = "Z\n", stderr = "" })
  same(text_of(buf), { "abcd", "Z" }, "line range")
end)

test("a same-line two-address range keeps the characterwise selection", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  vim.cmd("normal! \x1b")
  vim.cmd("1,1HarnessPasteMarkdown")
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "aZd" }, "same-line range")
end)

test("a line address does not reuse a blockwise selection", function()
  buffer({ "abcd", "efgh" })
  select_block()
  vim.cmd("normal! \x1b")
  vim.cmd("1HarnessCopyHtml")
  same(last_job().stdin, "abcd\n", "line")
  check(#notes == 0, "blockwise was reused")
end)

test("pid 1 is not signaled as every process the user can signal", function()
  local killed = {}
  vim.uv.kill = function(pid, signal)
    table.insert(killed, { pid = pid, signal = signal })
    return 0
  end
  buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  jobs[1].pid = 1
  press_paste_normal()
  same(killed, {}, "pid 1 was negated")
  check(jobs[1].killed == true, "the single process was not signaled")
  check(jobs[1].signal == "sigterm", "signal")
end)

test("cancelling the helper signals its process group", function()
  local killed = {}
  vim.uv.kill = function(pid, signal)
    table.insert(killed, { pid = pid, signal = signal })
    return 0
  end
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  same(jobs[1].env, { NEOVIM_HARNESS_PROCESS_GROUP = "1" }, "env")
  jobs[1].pid = 4242
  press_paste_normal()
  same(killed, { { pid = -4242, signal = "sigterm" } }, "group signal")
  check(jobs[1].killed == false, "the parent was signaled alone")
  jobs[1].on_exit({ code = 0, stdout = "OLD", stderr = "" })
  pump()
  same(text_of(buf), { "hello" }, "stale paste inserted")
  jobs[2].on_exit({ code = 0, stdout = "NEW", stderr = "" })
  pump()
  same(text_of(buf), { "heNEWllo" }, "newer paste")
end)

test("a newer paste cancels the previous request", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  press_paste_normal()
  check(#jobs == 2, "two pastes")
  check(jobs[1].killed == true, "old paste was not killed")
  check(jobs[1].signal == "sigterm", "signal")
  jobs[1].on_exit({ code = 0, stdout = "OLD", stderr = "" })
  pump()
  same(text_of(buf), { "hello" }, "stale paste inserted")
  check(#notes == 0, "stale callback notified " .. vim.inspect(notes))
  jobs[2].on_exit({ code = 0, stdout = "NEW", stderr = "" })
  pump()
  same(text_of(buf), { "heNEWllo" }, "newer paste")
  check(#notes == 0, "newer paste notified " .. vim.inspect(notes))
end)

test("a callback delivered by cancelling a paste does not insert", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  vim.system = function(cmd, opts, on_exit)
    local job = {
      cmd = vim.deepcopy(cmd),
      stdin = opts and opts.stdin,
      text = opts and opts.text,
      shell = opts and opts.shell,
      on_exit = on_exit,
      killed = false,
    }
    function job:kill(signal)
      self.killed = true
      self.signal = signal
      self.on_exit({ code = 0, stdout = "OLD", stderr = "" })
    end
    table.insert(jobs, job)
    return job
  end
  press_paste_normal()
  press_paste_normal()
  pump()
  same(text_of(buf), { "hello" }, "stale paste inserted")
  check(#notes == 0, "stale callback notified " .. vim.inspect(notes))
  jobs[2].on_exit({ code = 0, stdout = "NEW", stderr = "" })
  pump()
  same(text_of(buf), { "heNEWllo" }, "newer paste")
  check(#notes == 0, "newer paste notified " .. vim.inspect(notes))
end)

test("two pastes into an unchanged buffer both apply", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  finish({ code = 0, stdout = "A", stderr = "" })
  same(text_of(buf), { "heAllo" }, "first")
  same(vim.api.nvim_win_get_cursor(0), { 1, 2 }, "cursor")
  press_paste_normal()
  finish({ code = 0, stdout = "B", stderr = "" })
  same(text_of(buf), { "heABllo" }, "second")
  same(vim.api.nvim_win_get_cursor(0), { 1, 3 }, "cursor after second")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("a stale paste does not report a changed buffer", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  press_paste_normal()
  press_paste_normal()
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, { "hello!" })
  jobs[1].on_exit({ code = 0, stdout = "OLD", stderr = "" })
  pump()
  same(text_of(buf), { "hello!" }, "stale paste inserted")
  check(#notes == 0, "stale callback notified " .. vim.inspect(notes))
  jobs[2].on_exit({ code = 0, stdout = "NEW", stderr = "" })
  pump()
  same(text_of(buf), { "hello!" }, "newer paste inserted")
  same(notes, {
    {
      message = "The buffer changed during conversion. The result was not inserted.",
      level = vim.log.levels.ERROR,
    },
  }, "changedtick")
end)

test("a newer copy cancels the previous request", function()
  buffer({ "abcd" })
  select_chars(1, 1, 2)
  press_copy()
  same(jobs[1].stdin, "bc", "first copy")
  select_chars(1, 0, 0)
  press_copy()
  check(jobs[1].killed == true, "old copy was not killed")
  check(jobs[1].signal == "sigterm", "signal")
  jobs[1].on_exit({ code = 1, stdout = "", stderr = "old failure\n" })
  pump()
  check(#notes == 0, "stale copy notified " .. vim.inspect(notes))
  same(jobs[2].stdin, "a", "second copy")
  jobs[2].on_exit({ code = 0, stdout = "", stderr = "" })
  pump()
  check(#notes == 0, "newer copy notified " .. vim.inspect(notes))
end)

test("empty markdown leaves a visual selection unchanged", function()
  local buf = buffer({ "abcd" })
  select_chars(1, 1, 2)
  press_paste_visual()
  finish({ code = 0, stdout = "", stderr = "" })
  same(text_of(buf), { "abcd" }, "characterwise deleted")
  same(notes, {
    {
      message = "The converted Markdown is empty. The selection was left unchanged.",
      level = vim.log.levels.ERROR,
    },
  }, "empty characterwise")
  notes = {}
  jobs = {}
  buf = buffer({ "one", "two", "three" })
  select_lines(2, 2)
  press_paste_visual()
  finish({ code = 0, stdout = "", stderr = "" })
  same(text_of(buf), { "one", "two", "three" }, "linewise deleted")
  same(notes, {
    {
      message = "The converted Markdown is empty. The selection was left unchanged.",
      level = vim.log.levels.ERROR,
    },
  }, "empty linewise")
end)

test("empty markdown in normal mode does nothing", function()
  local buf = buffer({ "hello" })
  vim.api.nvim_win_set_cursor(0, { 1, 1 })
  local cursor = vim.api.nvim_win_get_cursor(0)
  press_paste_normal()
  finish({ code = 0, stdout = "", stderr = "" })
  same(text_of(buf), { "hello" }, "changed")
  same(vim.api.nvim_win_get_cursor(0), cursor, "cursor")
  check(#notes == 0, "notified " .. vim.inspect(notes))
end)

test("normal paste leaves the cursor on the inserted text", function()
  local emoji = "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}"
  local buf = buffer({ "a" .. emoji .. "b" })
  vim.cmd("normal! l")
  press_paste_normal()
  finish({ code = 0, stdout = "Z", stderr = "" })
  same(text_of(buf), { "a" .. emoji .. "Zb" }, "after emoji")
  same(vim.api.nvim_win_get_cursor(0), { 1, 19 }, "cursor")
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

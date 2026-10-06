-- Record a new session title, save named buffers, and quit.
-- The harness renames the directory only after this process exits.

local function fail(message)
  vim.notify(message, vim.log.levels.ERROR)
end

local function write_request(path, name)
  local handle, open_error = io.open(path, "w")
  if handle == nil then
    return false, open_error
  end
  local written, write_error = handle:write(name)
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

local function has_unnamed_modified_buffer()
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buf)
      and vim.api.nvim_buf_get_name(buf) == ""
      and vim.bo[buf].modified
    then
      return true
    end
  end
  return false
end

local function harness_rename()
  vim.ui.input({ prompt = "Session name: " }, function(name)
    if name == nil then
      return
    end
    local trimmed = vim.trim(name)
    if trimmed == "" then
      fail("Session name is empty.")
      return
    end
    local path = vim.env.NEOVIM_HARNESS_RENAME_FILE
    if path == nil or path == "" then
      fail("Rename request path is not set.")
      return
    end
    -- The input UI may still be open. Quit only after it has closed.
    vim.schedule(function()
      if has_unnamed_modified_buffer() then
        fail("Save unnamed buffers in this session, then run :HarnessRename again.")
        return
      end
      local saved, save_error = pcall(vim.cmd, "wall")
      if not saved then
        fail("Could not save buffers: " .. tostring(save_error))
        return
      end
      local recorded, record_error = write_request(path, trimmed)
      if not recorded then
        local message = "Could not record the session name."
        if record_error ~= nil and record_error ~= "" then
          message = message .. " " .. tostring(record_error)
        end
        fail(message)
        return
      end
      local quit, quit_error = pcall(vim.cmd, "qa")
      if not quit then
        local removed, remove_error = os.remove(path)
        if not removed then
          fail("Could not remove the rename request: " .. tostring(remove_error))
        end
        fail("Could not quit: " .. tostring(quit_error))
      end
    end)
  end)
end

pcall(vim.api.nvim_del_user_command, "HarnessRename")
vim.api.nvim_create_user_command("HarnessRename", harness_rename, {})

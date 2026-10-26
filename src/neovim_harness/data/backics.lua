local formats = {
    markdown = true,
    markdown_strict = true,
    djot = true,
    gfm = true,
    commonmark = true,
    commonmark_x = true
}


CodeBlock = function(elem)
    if not formats[FORMAT] then
        -- error(FORMAT .. " not supported")
        ---
        -- @no-op
        return elem
    end

    local text, classes, attr = elem.text, elem.classes, elem.attr

    local wd = 2
    for t in text:gmatch("%`+") do
        if #t > wd then
            wd = #t
        end
    end
    local fence = ('`'):rep(wd + 1)
    local block = fence .. "\n" .. text .. "\n" .. fence
    return pandoc.RawBlock(FORMAT, block)
end


--- A GFM table cell holds inline content only.  Returns the cell's inlines
-- split into runs at every block boundary and at every hard break, or nil
-- when the cell holds a block that a pipe table cannot express.  The runs
-- are joined with a literal `<br>` once each one is written.
local function cell_runs(cell)
    local runs = {}
    local current = {}

    local function finish_run()
        table.insert(runs, current)
        current = {}
    end

    for index, block in ipairs(cell.contents) do
        if block.t ~= "Plain" and block.t ~= "Para" then
            return nil
        end
        if index > 1 then
            finish_run()
        end
        for _, inline in ipairs(block.content) do
            if inline.t == "LineBreak" then
                finish_run()
            else
                table.insert(current, inline)
            end
        end
    end
    finish_run()
    return runs
end


--- A bare `|` splits a cell, and the GFM writer escapes it in `Str` text only.
-- Escaping at the text level with a backslash count keeps `\|` and `\\\|`
-- and also escapes the pipe in a code span or in a link title.
local function escape_pipes(text)
    local escaped = {}
    local backslashes = 0
    for index = 1, #text do
        local char = text:sub(index, index)
        if char == "|" then
            if backslashes % 2 == 0 then
                table.insert(escaped, "\\")
            end
            backslashes = 0
        elseif char == "\\" then
            backslashes = backslashes + 1
        else
            backslashes = 0
        end
        table.insert(escaped, char)
    end
    return table.concat(escaped)
end


local function gfm_run(inlines)
    -- Raw HTML is disabled here, so an element attribute is dropped exactly as
    -- it is everywhere else in this output.  The `<br>` between runs is added
    -- after writing, so it never goes through the writer and is never dropped.
    local rendered = pandoc.write(pandoc.Pandoc({ pandoc.Plain(inlines) }), "gfm-raw_html", {
        wrap_text = "none"
    })
    rendered = rendered:gsub("^%s+", "")
    rendered = rendered:gsub("%s+$", "")
    return rendered
end


local function gfm_cell(cell)
    local runs = cell_runs(cell)
    if runs == nil then
        return nil
    end
    local rendered = {}
    for index, inlines in ipairs(runs) do
        rendered[index] = gfm_run(inlines)
    end
    return escape_pipes(table.concat(rendered, "<br>"))
end


local function table_caption_is_empty(caption)
    if caption.long ~= nil then
        return #caption.long == 0
    end
    return #caption == 0
end


local function table_is_rectangular(tbl)
    local columns = #tbl.colspecs

    local function row_is_rectangular(row)
        if #row.cells ~= columns then
            return false
        end
        for _, cell in ipairs(row.cells) do
            if cell.col_span ~= 1 or cell.row_span ~= 1 then
                return false
            end
        end
        return true
    end

    for _, row in ipairs(tbl.head.rows) do
        if not row_is_rectangular(row) then
            return false
        end
    end
    for _, body in ipairs(tbl.bodies) do
        for _, row in ipairs(body.head) do
            if not row_is_rectangular(row) then
                return false
            end
        end
        for _, row in ipairs(body.body) do
            if not row_is_rectangular(row) then
                return false
            end
        end
    end
    for _, row in ipairs(tbl.foot.rows) do
        if not row_is_rectangular(row) then
            return false
        end
    end
    return true
end


local function table_row(row, columns)
    local cells = {}
    for index = 1, columns do
        local cell = row.cells[index]
        local rendered = ""
        if cell ~= nil then
            -- `cell and gfm_cell(cell) or ""` would turn the nil that means
            -- "this cell cannot be a pipe-table cell" back into "".
            rendered = gfm_cell(cell)
            if rendered == nil then
                return nil
            end
        end
        cells[index] = rendered
    end
    return "| " .. table.concat(cells, " | ") .. " |"
end


local function table_separator(tbl, header)
    local cells = {}
    for index, colspec in ipairs(tbl.colspecs) do
        -- The column spec is authoritative; a reader fills in the cell
        -- alignment only when that one cell carried the attribute.
        local alignment = colspec[1]
        if alignment == pandoc.AlignDefault then
            local cell = header.cells[index]
            if cell ~= nil then
                alignment = cell.alignment
            end
        end
        if alignment == pandoc.AlignLeft then
            cells[index] = ":---"
        elseif alignment == pandoc.AlignCenter then
            cells[index] = ":---:"
        elseif alignment == pandoc.AlignRight then
            cells[index] = "---:"
        else
            cells[index] = "---"
        end
    end
    return "| " .. table.concat(cells, " | ") .. " |"
end


Table = function(elem)
    -- Pandoc before 2.10 has a different Table shape without head, bodies, or
    -- foot.  Leave such a table to the writer.
    if FORMAT ~= "gfm"
        or elem.head == nil
        or elem.bodies == nil
        or elem.foot == nil then
        return elem
    end
    if not table_caption_is_empty(elem.caption) then
        return elem
    end
    if not table_is_rectangular(elem) or #elem.head.rows == 0 then
        return elem
    end

    local columns = #elem.colspecs
    local header = table_row(elem.head.rows[1], columns)
    if header == nil then
        return elem
    end
    local lines = { header, table_separator(elem, elem.head.rows[1]) }

    -- GFM has one header row.  Every other header row, including a row that
    -- heads a table body, becomes an ordinary row so that no text is lost.
    local rows = {}
    for index = 2, #elem.head.rows do
        table.insert(rows, elem.head.rows[index])
    end
    for _, body in ipairs(elem.bodies) do
        for _, row in ipairs(body.head) do
            table.insert(rows, row)
        end
        for _, row in ipairs(body.body) do
            table.insert(rows, row)
        end
    end
    for _, row in ipairs(elem.foot.rows) do
        table.insert(rows, row)
    end

    for _, row in ipairs(rows) do
        local rendered = table_row(row, columns)
        if rendered == nil then
            return elem
        end
        table.insert(lines, rendered)
    end

    return pandoc.RawBlock("gfm", table.concat(lines, "\n") .. "\n")
end

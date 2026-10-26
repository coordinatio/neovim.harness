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


--- True when the inlines hold a footnote reference at any depth.  Pandoc nests
-- it inside a Superscript or a Link in its own footnote HTML.
local function holds_note(inlines)
    local found = false
    pandoc.Inlines(inlines):walk({
        Note = function(note)
            found = true
            return note
        end
    })
    return found
end


--- Flattens the transparent containers a cell may hold into the blocks they
-- wrap.  The HTML reader keeps a `<div>` or a `<section>` inside a cell as a
-- `Div`, and a cell whose only wrapper is one of those still holds inline
-- content.  Everything else, such as a list, a code block, a header, or a
-- block quote, is returned as it is for the caller to reject.
local function flatten_containers(blocks, flat)
    for _, block in ipairs(blocks) do
        if block.t == "Div" then
            flatten_containers(block.content, flat)
        else
            table.insert(flat, block)
        end
    end
    return flat
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

    for index, block in ipairs(flatten_containers(cell.contents, {})) do
        if block.t ~= "Plain" and block.t ~= "Para" then
            return nil
        end
        -- The writer hoists a note definition only when the cell is part of the
        -- document it writes.  A cell written on its own would put the
        -- definition inside the row and number it from one, so leave such a
        -- table to Pandoc, which keeps `| a[^1] | b |` and the definition.
        if holds_note(block.content) then
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


--- `|` and `\` in `Str` text cannot be left to the writer.  It drops a pipe
-- that follows an odd run of backslashes, so `a\|b` loses its pipe before the
-- text could be escaped; and it leaves a backslash before a letter alone,
-- while the Markdown reader this project uses turns `\Word` into raw TeX that
-- the HTML writer then drops, so `C:\Users\me` loses everything from the
-- first backslash on.  Writing the two characters as raw inlines makes them
-- unambiguous: `\|` is one pipe and `\\` is one backslash.  `Code` text and
-- link destinations are left alone, because a reader keeps a pipe in a code
-- span and the writer percent-encodes a pipe in a destination.
local function protect_str(str)
    local protected = {}
    local segment = {}

    local function flush()
        if #segment > 0 then
            table.insert(protected, pandoc.Str(table.concat(segment)))
            segment = {}
        end
    end

    for index = 1, #str.text do
        local char = str.text:sub(index, index)
        if char == "|" then
            flush()
            table.insert(protected, pandoc.RawInline("gfm", "\\|"))
        elseif char == "\\" then
            flush()
            table.insert(protected, pandoc.RawInline("gfm", "\\\\"))
        else
            table.insert(segment, char)
        end
    end
    flush()
    return protected
end


--- A link or image title is written between quotes on the row itself, so a
-- line break there splits the row and a pipe there splits the cell.  Pandoc
-- writes the title verbatim apart from its own quoting, so the title gets the
-- same treatment as text: a line break becomes a space, then a backslash and
-- a pipe are escaped.
local function protect_title(title)
    if title == nil then
        return title
    end
    title = title:gsub("[\r\n\t]", " ")
    title = title:gsub("\\", "\\\\")
    return (title:gsub("|", "\\|"))
end


local function gfm_run(inlines)
    -- Raw HTML is disabled here, so an element attribute is dropped exactly as
    -- it is everywhere else in this output.  The `<br>` between runs is added
    -- after writing, so it never goes through the writer and is never dropped.
    -- A hard break inside Strong, Emph, Span, Link, or any other container is
    -- that same `<br>`: the writer would otherwise emit a backslash and a
    -- newline and split the row.
    local lifted = pandoc.Inlines(inlines):walk({
        LineBreak = function()
            return pandoc.RawInline("gfm", "<br>")
        end,
        Link = function(link)
            link.title = protect_title(link.title)
            return link
        end,
        Image = function(image)
            image.title = protect_title(image.title)
            return image
        end,
        Str = protect_str
    })
    local rendered = pandoc.write(pandoc.Pandoc({ pandoc.Plain(lifted) }), "gfm-raw_html", {
        wrap_text = "none"
    })
    rendered = rendered:gsub("^%s+", "")
    rendered = rendered:gsub("%s+$", "")
    -- A backstop: with the titles sanitized above, nothing else is known to
    -- write a second line, but a row that did split would be worse than
    -- leaving the table to Pandoc.
    if rendered:find("\n", 1, true) then
        return nil
    end
    return rendered
end


local function gfm_cell(cell)
    local runs = cell_runs(cell)
    if runs == nil then
        return nil
    end
    local rendered = {}
    for index, inlines in ipairs(runs) do
        local run = gfm_run(inlines)
        if run == nil then
            return nil
        end
        rendered[index] = run
    end
    return table.concat(rendered, "<br>")
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


local function empty_row(columns)
    local cells = {}
    for index = 1, columns do
        cells[index] = ""
    end
    return "| " .. table.concat(cells, " | ") .. " |"
end


local function table_separator(tbl, header)
    local cells = {}
    for index, colspec in ipairs(tbl.colspecs) do
        -- The column spec is authoritative; a reader fills in the cell
        -- alignment only when that one cell carried the attribute.
        local alignment = colspec[1]
        if alignment == pandoc.AlignDefault and header ~= nil then
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
    local columns = #elem.colspecs
    if not table_is_rectangular(elem) or columns == 0 then
        return elem
    end

    -- GFM has exactly one header row.  The head normally holds it, but a table
    -- written without `<thead>` keeps its header cells in the body's head, so
    -- take the first row of either and demote every other header row to a body
    -- row so that no text is lost.
    local header = nil
    local rows = {}
    for _, row in ipairs(elem.head.rows) do
        if header == nil then
            header = row
        else
            table.insert(rows, row)
        end
    end
    for _, body in ipairs(elem.bodies) do
        for _, row in ipairs(body.head) do
            if header == nil then
                header = row
            else
                table.insert(rows, row)
            end
        end
        for _, row in ipairs(body.body) do
            table.insert(rows, row)
        end
    end
    for _, row in ipairs(elem.foot.rows) do
        table.insert(rows, row)
    end
    if header == nil and #rows == 0 then
        return elem
    end

    local header_line = empty_row(columns)
    if header ~= nil then
        header_line = table_row(header, columns)
        if header_line == nil then
            return elem
        end
    end
    local lines = { header_line, table_separator(elem, header) }

    for _, row in ipairs(rows) do
        local rendered = table_row(row, columns)
        if rendered == nil then
            return elem
        end
        table.insert(lines, rendered)
    end

    return pandoc.RawBlock("gfm", table.concat(lines, "\n") .. "\n")
end

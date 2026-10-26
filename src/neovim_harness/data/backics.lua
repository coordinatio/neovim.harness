local formats = {
    markdown = true,
    markdown_strict = true,
    djot = true,
    gfm = true,
    ["gfm-raw_html"] = true,
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


local function gfm_cell(cell)
    -- A GFM table cell is an inline-sized block.  Rendering it separately
    -- keeps emphasis, links, code spans, and escaped pipes intact.
    local rendered = pandoc.write(pandoc.Pandoc(cell.contents), "gfm-raw_html", {
        wrap_text = "none"
    })
    rendered = rendered:gsub("^%s+", "")
    -- A hard break cannot be represented by the GFM table writer.  Keep it
    -- as HTML inside the cell, which is valid GFM and survives the next pass.
    local hard_break = string.char(92) .. "\n"
    rendered = rendered:gsub(hard_break, "<br>")
    rendered = rendered:gsub("\n+$", "")
    rendered = rendered:gsub("\n+", "<br>")
    rendered = rendered:gsub("%s+$", "")
    return rendered
end


local function table_caption_is_empty(caption)
    if caption == nil then
        return true
    end
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
        cells[index] = cell and gfm_cell(cell) or ""
    end
    return "| " .. table.concat(cells, " | ") .. " |"
end


local function table_separator(tbl, header)
    local cells = {}
    for index = 1, #tbl.colspecs do
        local alignment = header.cells[index].alignment
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
    if (FORMAT ~= "gfm" and FORMAT ~= "gfm-raw_html")
        or not table_caption_is_empty(elem.caption) then
        return elem
    end
    if not table_is_rectangular(elem) or #elem.head.rows == 0 then
        return elem
    end

    local columns = #elem.colspecs
    local lines = {
        table_row(elem.head.rows[1], columns),
        table_separator(elem, elem.head.rows[1])
    }
    for _, body in ipairs(elem.bodies) do
        for _, row in ipairs(body.body) do
            table.insert(lines, table_row(row, columns))
        end
    end
    for _, row in ipairs(elem.foot.rows) do
        table.insert(lines, table_row(row, columns))
    end

    return pandoc.RawBlock("gfm", table.concat(lines, "\n") .. "\n")
end

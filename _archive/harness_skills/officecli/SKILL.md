---
name: officecli
description: "Create, analyze, proofread, and modify Office documents (.docx, .xlsx, .pptx) using the officecli CLI tool. Use when the user wants to create, inspect, check formatting, find issues, add charts, tables, or slides, or modify Office documents programmatically."
version: 1.0.0
domain: documents
mode: prompt
tags: [office, docx, xlsx, pptx, documents, excel, word, powerpoint, officecli]
source: "https://github.com/iOfficeAI/OfficeCLI"
required_tools: [officecli_create_document, officecli_add_element, officecli_view_document, officecli_set_properties, officecli_merge_template]
dependencies: []
---

# OfficeCLI

AI-friendly CLI for .docx, .xlsx, .pptx. Single binary, no dependencies, no Office installation needed.

## Available Tools (TitanShift Harness)

| Tool | Purpose |
|------|---------|
| `officecli_create_document` | Create a blank .docx/.xlsx/.pptx file |
| `officecli_add_element` | Add slide, paragraph, chart, table, image, or other element |
| `officecli_view_document` | Inspect document (outline, stats, text, issues, annotated) |
| `officecli_set_properties` | Modify element properties (text, font, color, fill, value, find/replace) |
| `officecli_merge_template` | Merge JSON data into placeholder tokens (mail merge / templating) |
| `officecli_batch` | Execute multiple operations in one save cycle (most efficient for bulk edits) |

## Strategy

**L1 (read) → L2 (DOM edit) → L3 (raw XML)**. Always prefer higher layers. All tool calls include `--json` for structured output.

## Typical Workflows

### Create a Word report
```
officecli_create_document  →  path=outputs/report.docx
officecli_add_element      →  path=outputs/report.docx, parent=/body, type=paragraph, props={text:"Executive Summary", style:Heading1}
officecli_add_element      →  path=outputs/report.docx, parent=/body, type=paragraph, props={text:"Revenue grew 25% YoY."}
officecli_view_document    →  path=outputs/report.docx, mode=issues
```

### Create a PowerPoint deck
```
officecli_create_document  →  path=outputs/deck.pptx
officecli_add_element      →  path=outputs/deck.pptx, parent=/, type=slide, props={title:"Q4 Report", background:1A1A2E}
officecli_add_element      →  path=outputs/deck.pptx, parent=/slide[1], type=shape, props={text:"Revenue grew 25%", x:2cm, y:5cm, font:Arial, size:24, color:FFFFFF}
```

### Populate a template
```
officecli_merge_template   →  path=templates/invoice_template.docx, data={{{CLIENT_NAME}}:"Acme Corp", {{DATE}}:"2026-04-18", {{TOTAL}}:"$12,500"}
```

### Bulk edits (most efficient)
```
officecli_batch  →  path=outputs/report.docx, operations=[
  {command:set, path:/, props:{find:"draft", replace:"final"}},
  {command:set, path:/body/p[1], props:{bold:true, fontSize:14pt}},
  {command:add, parent:/body, type:paragraph, props:{text:"Appendix"}}
]
```

## Path Conventions

- Paths are **1-based** (XPath): `/body/p[3]` = third paragraph
- Always **single-quote** paths with brackets in shell: `'/slide[1]'`
- Prefer **stable ID paths** over positional when available: `/slide[1]/shape[@id=550950021]`
- `/` = document root / whole-document scope for find/replace

## Element Types Reference

| Format | Element types |
|--------|--------------|
| **docx** | paragraph, run, table, row, cell, image, header, footer, section, bookmark, comment, footnote, chart, hyperlink, toc, watermark |
| **pptx** | slide, shape, picture, chart, table, row, connector, group, video, equation, notes |
| **xlsx** | sheet, row, cell, chart, image, table, namedrange, pivottable, sparkline, validation, autofilter |

## Common Props

| Prop | Applies to | Examples |
|------|-----------|---------|
| `text` | paragraph, shape, cell | `text=Executive Summary` |
| `style` | paragraph | `style=Heading1`, `style=Normal` |
| `bold`, `italic`, `underline` | run, paragraph | `bold=true` |
| `fontSize` | run, paragraph | `fontSize=14pt` |
| `color` | run, shape | `color=FF0000`, `color=red` |
| `fill` / `background` | shape, slide | `fill=1A1A2E` |
| `value` | cell | `value=42`, `value==SUM(A1:A10)` |
| `find` + `replace` | set (any scope) | `find=draft`, `replace=final` |
| `x`, `y`, `width`, `height` | shape, picture | `x=2cm`, `y=5cm` |
| `title` | slide | `title=Q4 Revenue` |

## Validation

Always run `officecli_view_document` with `mode=issues` before delivering a file to the user. Fix any reported issues with `officecli_set_properties` or `officecli_batch`.

## Help Discovery

When unsure about property names or command syntax, use `officecli_view_document` with mode=outline first to understand the document structure, then use element paths from the outline response.

## Performance

For sessions editing the same file many times, prefer `officecli_batch` with multiple operations over individual tool calls. The binary auto-starts a resident process (60s idle timeout) for lower file I/O overhead.

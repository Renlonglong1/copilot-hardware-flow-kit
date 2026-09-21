---
name: generic-large-file-writer
description: 'Write large files (500+ lines) by splitting content into sequential chunks to avoid context window overflow. USE WHEN: creating large markdown documents, analysis reports, specification documents, code files, or any output that exceeds ~300 lines. Also use when a previous attempt to create a file failed due to context length. Handles: planning document outline first, writing each section as a separate chunk via create_file then append, ensuring continuity between chunks. KEYWORDS: large file, long document, split write, chunked write, 大文件, 长文档, 分段写入, 拆分写入, context too long, 上下文太长.'
---

# Large File Writer Skill

Write large files (500+ lines) by splitting content into sequential chunks, avoiding context window overflow.

## When to Use

- Creating any document/file expected to exceed ~300 lines
- A previous attempt to create a large file was cut off or failed due to context limits
- User explicitly says "上下文太长", "context too long", "split into chunks"
- Writing comprehensive analysis documents, spec mappings, reports with many sections

## Core Strategy

**Never try to generate a 1000+ line file in a single tool call or a single mental pass.**

Instead:

1. **Plan first** — Create a detailed outline with estimated line counts per section
2. **Write in chunks** — Each chunk is one logical section (100-250 lines max)
3. **Use create_file for chunk 1**, then **append subsequent chunks via terminal**
4. **Track progress** — Use todo list to mark each section as it's written

## Step-by-Step Procedure

### Step 1: Plan the Document Structure

Before writing any content, create a section outline:

```
Section 1: Title & TOC (~30 lines)
Section 2: Architecture Overview (~80 lines)
Section 3: Feature A Details (~120 lines)
Section 4: Feature B Details (~150 lines)
...
```

Use `manage_todo_list` to create a todo item for each section.

### Step 2: Write Chunk 1 (create_file)

Use `create_file` to write the first chunk (typically: title, TOC, and first 1-2 sections).

**Keep each chunk under 250 lines** to stay well within tool call limits.

### Step 3: Append Subsequent Chunks (terminal)

For each remaining section, use the terminal to append:

```bash
cat >> /path/to/file.md << 'CHUNK_END'
<content of this section>
CHUNK_END
```

**Critical rules for heredoc append:**
- Use a unique delimiter like `'CHUNK_END'` (single-quoted to prevent variable expansion)
- Make sure the delimiter does NOT appear inside the content
- If content contains single quotes or backticks, use a different delimiter like `'SECTION_EOF'`
- If content contains heredoc-like patterns, write to a temp file first and use `cat temp >> target`

### Step 4: Verify

After all chunks are written:

```bash
wc -l /path/to/file.md          # Check total line count
head -20 /path/to/file.md       # Verify start
tail -20 /path/to/file.md       # Verify end
grep -c "^#" /path/to/file.md   # Count section headers
```

## Chunk Size Guidelines

| Content Type | Max Lines Per Chunk | Notes |
|---|---|---|
| Markdown prose | 200-250 | Paragraphs, tables, lists |
| Code blocks | 150-200 | Include surrounding context |
| Mixed (prose + code) | 150-200 | Code blocks inflate token count |
| Tables with wide columns | 100-150 | Wide tables use more tokens per line |

## Handling Special Characters in Heredoc

If the content contains characters that conflict with heredoc:

### Option A: Escape-safe delimiter
```bash
cat >> file.md << 'UNIQUE_CHUNK_842'
content here...
UNIQUE_CHUNK_842
```

### Option B: Temp file approach (safest for complex content)
```bash
# Write chunk to temp file first
cat > /tmp/chunk_N.md << 'EOF_CHUNK'
content here...
EOF_CHUNK

# Append temp to target
cat /tmp/chunk_N.md >> /path/to/file.md
rm /tmp/chunk_N.md
```

### Option C: Python append (best for content with all types of quotes)
```bash
python3 -c "
content = '''
your content here
'''
with open('/path/to/file.md', 'a') as f:
    f.write(content)
"
```

## Example: Writing a 1200-line Analysis Document

```
Plan:
  Section 1: Header + TOC (40 lines) → create_file
  Section 2: Architecture (100 lines) → cat >> heredoc
  Section 3: Feature Analysis 3.1-3.4 (200 lines) → cat >> heredoc
  Section 4: Feature Analysis 3.5-3.8 (200 lines) → cat >> heredoc
  Section 5: Feature Analysis 3.9-3.14 (200 lines) → cat >> heredoc
  Section 6: Status Summary Table (80 lines) → cat >> heredoc
  Section 7: Gap Analysis (100 lines) → cat >> heredoc
  Section 8: In-band Implementation (150 lines) → cat >> heredoc
  Section 9: Firmware Details (130 lines) → cat >> heredoc
  Total: ~1200 lines in 9 chunks
```

## Anti-Patterns (DO NOT)

- ❌ Try to write 500+ lines in a single `create_file` call
- ❌ Generate all content mentally before starting to write
- ❌ Skip the planning step — you WILL lose track of structure
- ❌ Use `replace_string_in_file` to build a large file incrementally (slow, error-prone)
- ❌ Forget to verify the final file after all chunks are written

## Continuity Between Chunks

Each chunk should:
1. **Start where the previous chunk ended** — don't repeat headers or content
2. **Maintain consistent formatting** — same heading level scheme, table style, etc.
3. **Cross-reference correctly** — if chunk 3 references "§2.1", make sure that section exists in chunk 1 or 2

## Recovery

If a chunk write fails mid-way:
1. Check what was written: `tail -30 /path/to/file.md`
2. If partial content was appended, truncate to the last complete section:
   ```bash
   # Find the line number of the last complete section header
   grep -n "^##" /path/to/file.md | tail -5
   # Truncate to that point if needed
   head -n <LINE_NUMBER> /path/to/file.md > /tmp/file_clean.md
   mv /tmp/file_clean.md /path/to/file.md
   ```
3. Re-append the failed chunk from the correct starting point

---
name: bios-locate-knob
description: "Locate a BIOS setup knob's position in EDK II VFR/HFR form pages and analyze its constraints. Use this skill whenever a user asks to find, locate, or search for a setup knob in BIOS code — including phrasing like 'where is this knob', 'find knob X', 'which form has knob Y', 'locate setup option', 'knob position in BIOS menu', or any request involving searching VFR/HFR/UNI files for setup question definitions. Also use when the user wants to know what controls the visibility/availability of a knob, questions like 'when is this knob hidden?', 'when is this knob disabled?', or 'what are the constraints on this knob?' The skill can fuzzy-match by searching display text and help strings in UNI files when the user describes a knob's function vaguely (e.g., 'the memory frequency option', 'S3 sleep knob'). The skill will analyze suppressif, grayoutif, and disableif conditions to identify all constraints affecting the knob, and present them in a hierarchical structure with English translations."
---

# BIOS Locate Knob

Locate a BIOS setup knob in EDK II VFR/HFR source code: find where it's defined, which form page contains it, and estimate its visual position on the page.

## Step 0: Validate Workspace

Determine if the current workspace (or a directory the user has open) is a BIOS code tree. Look for EDK II markers like `*.dsc`, `*.fdf`, directories named `Platform/`, `Silicon/`, `Intel/`, `Edk2/`, or files like `Conf/target.txt`.

- If markers are found → use that directory as BIOS_ROOT and proceed.
- If NOT found → ask the user: "This workspace doesn't look like a BIOS code directory. Please provide the absolute path to your BIOS code root."

Store the resolved path as `BIOS_ROOT` for all subsequent searches.

## Step 1: Search for the Knob Definition

Search under BIOS_ROOT for the knob. The user may provide input at varying levels of precision — from an exact variable name to a vague functional description. Classify the input first, then use the matching search strategy.

### Input Classification

| Input Type | Example | Strategy |
|------------|---------|----------|
| **Exact varid name** | `EnforceDdrMemoryFreqPor` | Direct search in VFR/HFR |
| **STRING_TOKEN name** | `STR_ENFORCE_DDR_MEMORY_FREQ_POR_PROMPT` | Direct search in VFR/HFR |
| **Exact display text** | `"Enforce DDR Memory Frequency POR"` | Search UNI → get STR_ID → search VFR/HFR |
| **Fuzzy description** | "the knob for memory frequency", "S3 sleep related option", "DDR speed enforcement" | Keyword search in UNI → candidate list → confirm with user |

To classify: if the input looks like a C identifier (CamelCase, underscores, no spaces) it's likely an exact name. If it contains spaces, natural language, or reads like a description of functionality, treat it as fuzzy.

### Search Strategy A: Exact Name (varid or STRING_TOKEN)

Try these patterns in order until you find matches:
1. `varid` containing the knob name (catches `varid = STRUCT.KnobName`)
2. `STRING_TOKEN` containing the knob name (catches prompt references)

### Search Strategy B: Display Text (exact or partial)

Search `*.uni` files for the text. Match against both `PROMPT` and `HELP` string definitions — the help text often contains more descriptive language. Extract the `STR_*_PROMPT` identifier, then search VFR/HFR files for `STRING_TOKEN(<that identifier>)`.

### Search Strategy C: Fuzzy / Functional Description

When the user describes the knob's function rather than its name (e.g., "memory frequency enforcement", "the option to enable S3 sleep", "DDR speed setting"), follow this process:

1. **Extract keywords** from the user's description. Think about what words would realistically appear in the knob's display text or help text in a BIOS setup menu. For example:
   - "memory frequency enforcement" → search for `frequency`, `enforce`, `DDR`
   - "S3 sleep option" → search for `S3`, `sleep`, `ACPI`
   - "directory mode setting" → search for `directory`, `mode`

2. **Search `*.uni` files** for these keywords. Look at both `#string STR_*_PROMPT` lines (the knob's visible label) and `#string STR_*_HELP` lines (the knob's tooltip/description, which often contains more context about what the knob does). Use multiple keywords combined if a single keyword returns too many results.

3. **Build a candidate list.** For each matching UNI string, extract:
   - The `STR_*` identifier
   - The display text
   - Whether it's a PROMPT or HELP string

4. **Filter to actual knobs.** Not every string in a UNI file is a knob — some are form titles, subtitles, or option values. Focus on strings ending in `_PROMPT` or `_HELP`, since those correspond to question elements. For each candidate `STR_*_PROMPT`, verify it is actually used in a `oneof`/`checkbox`/`numeric`/etc. definition by searching VFR/HFR files for `STRING_TOKEN(<candidate>)`.

5. **If multiple candidates match**, present the top candidates (up to 5) to the user with their display text and help text, and ask which one they meant. Format like:
   ```
   Found multiple matching knobs:
   1. "Enforce DDR Memory Frequency POR" — Enforces Plan Of Record restrictions for DDR frequency programming.
   2. "Memory Frequency" — Sets the memory operating frequency.
   3. "DDR Frequency Limit" — Limits maximum DDR frequency.
   Which one are you looking for? (enter number or refine your search)
   ```

6. **If no matches are found**, try broadening the search: use fewer keywords, try synonyms, or search with individual words instead of phrases. If still nothing, tell the user and suggest browsing the relevant UNI files.

### After Finding the Knob

For each match found, read the full knob definition (from `oneof`/`checkbox`/`numeric`/etc. to its closing `endoneof`/`endcheckbox`/`endnumeric`/etc.) and record:
- **File path and line number**
- **Knob type**: `oneof`, `checkbox`, `numeric`, `orderedlist`, `string`, `date`, `time`
- **Varid**: the full `STRUCT.FieldName`
- **Prompt**: the `STRING_TOKEN(STR_...)` reference
- **Help**: the `STRING_TOKEN(STR_...)` reference
- **Options or range**: for `oneof` list all `option text = ... value = ...`; for `numeric` list `minimum`/`maximum`/`step`
- **Conditional wrappers**: capture the full text of any `suppressif`, `grayoutif`, or `disableif` conditions **(you will analyze these in detail in Step 1.5)**

Then search `*.uni` files for the prompt and help STRING_TOKEN identifiers to resolve their display text.

If the knob is not found after all strategies, suggest partial matches or related STRING_TOKEN names before giving up.

## Step 1.5: Analyze Knob Constraints

**Critical:** This step extracts and translates the conditional statements that affect the knob's visibility and state. A knob may be wrapped in one or more conditional statements. Your goal is to parse all such conditions, organize them hierarchically, and translate them into human-readable English.

### Identify Conditional Wrappers

When you read the full knob definition (from Step 1), look for these VFR control structures **either immediately surrounding the knob OR appearing as outer wrappers**:

- `suppressif ( <condition> );` followed by `endif;` — **Hides the knob** if the condition is TRUE
- `grayoutif ( <condition> );` followed by `endif;` — **Disables (grays out) the knob** if the condition is TRUE  
- `disableif ( <condition> );` followed by `endif;` — **Disables the knob** if the condition is TRUE

Multiple wrappers can nest: a `suppressif` may contain a `grayoutif` which contains the actual knob definition.

### Parse Conditions

Conditions are built from boolean operators and comparison operators. Common patterns:

| Pattern | Meaning |
|---------|---------|
| `ideqval <STRUCT>.<Field> == <VALUE>` | Equality check: **Field equals VALUE** |
| `NOT ideqval <STRUCT>.<Field> == <VALUE>` | Negation: **Field does NOT equal VALUE** |
| <condition1> OR <condition2> | Logical OR: **Either condition is true** |
| <condition1> AND <condition2> | Logical AND: **Both conditions are true** |
| `idneqval <STRUCT>.<Field> <VALUE>` | Inequality: **Field does not equal VALUE** (alternative syntax) |

### Translate Conditions to Natural Language

Convert each condition into a clause following this pattern:

- For **ideqval**: `"<STRUCT.Field> equals <VALUE>"` or shorter `"<Field> is <VALUE>"`
- For **NOT ideqval**: `"<Field> is NOT <VALUE>"` or `"<Field> does not equal <VALUE>"`
- For **logical operators**: use "AND" "OR" at the top level, and **indent nested sub-conditions**

### Build Hierarchical Constraint List

If multiple wrappers nest around a knob, present them in **hierarchical order from outermost to innermost**, with indentation showing the nesting depth:

```
Constraint 1: suppressif (condition)
  - Outer condition: <translation>
      AND
  - Inner grayoutif (condition)
      - Grayout condition: <translation>
          OR
      - Sub-condition: <translation>
```

### Handle Complex Boolean Expressions

For multi-part conditions with multiple operators, preserve the operator precedence and nesting from the original VFR source:

**Example:**
```
grayoutif ((ideqval SOCKET_MEM_DECODE_CONFIGURATION.VirtualNumaEnable == SETUP_ENABLE) OR
           (NOT ideqval SOCKET_MEM_DECODE_CONFIGURATION.GroupMbaMode == GROUP_MBA_MODE_DISABLE));
```

Translates to:
```
- Grayout Condition (grayoutif):
    - VirtualNumaEnable equals SETUP_ENABLE
      OR
    - GroupMbaMode does NOT equal GROUP_MBA_MODE_DISABLE
```

### Document the Constraint Impact

For each wrapper, state its effect:

- **suppressif**: "Hidden if [condition is true]"
- **grayoutif**: "Disabled (unavailable for editing) if [condition is true]"
- **disableif**: "Disabled if [condition is true]"

### Summary Presentation

At the end, produce a **Constraints Summary** that consolidates all conditions into a concise narrative suitable for inclusion in the output report:

```
## Constraints
**Visibility:**
  - Hidden if CpuType is NOT CPU_DMRHD

**Interaction State:**
  - Disabled if VirtualNumaEnable equals SETUP_ENABLE
    OR GroupMbaMode does NOT equal GROUP_MBA_MODE_DISABLE
```

If there are NO conditional wrappers, state: **"None — knob is always visible and enabled."**

## Step 2: Find the Containing Form

From the knob's file and line number, search **backwards** toward the beginning of the file for the nearest `form formid =` statement. This tells you which form page the knob lives on.

**Important**: `.hfr` files are often `#include`d into a `.vfr` file between a `form` and `endform`. If you reach the beginning of an `.hfr` file without finding a `form` definition:
1. Search `*.vfr` files for `#include` of this `.hfr` filename
2. In the `.vfr` file, find the `#include` line
3. Search backwards from that `#include` line to find the `form formid =`

Extract the form's `title = STRING_TOKEN(<STR_ID>)`.

## Step 3: Resolve the Form Title

Search `*.uni` files for the `STR_ID` from the form title to get the human-readable text (e.g., `"Memory Configuration"`).

## Step 4: Find the Form Boundary

From the `form formid =` line, search **forward** to find the matching `endform;`. Record:
- The `form formid =` line number and file
- The `endform;` line number and file
- Any `#include` directives between them (these inject additional content into the form)

## Step 5: Estimate the Knob's Position

Count **opcodes** to determine the knob's position on the form page. Each opcode corresponds to one rendered setup item (knob) in the BIOS UI, and each opcode is identified by a `varid =` pattern in the VFR/HFR source. This is the most accurate method because it directly counts the actual interactive elements the user sees on the form page, regardless of how many source lines each knob definition occupies (comments, options, conditional wrappers, blank lines are all irrelevant to the rendered item count).

### Algorithm: Opcode-Based Position

1. **Collect all `varid =` occurrences** within the form boundary (from `form formid =` to `endform;`). If the form spans multiple files via `#include`, also count `varid =` in each included `.hfr` file.
2. **Total opcode count (M)** = number of `varid =` occurrences in the entire form.
3. **Knob index (N)** = the ordinal position of the target knob's `varid =` among all opcodes, counting from the form start. The first `varid =` after `form formid =` is opcode 1.
4. **Position percentage** = `N / M × 100`

**Same-file form**: Count `varid =` from the `form` line to `endform;` within the same file.

**Cross-file form** (form in .vfr, knobs in included .hfr files): Walk the .vfr file from `form formid =` to `endform;`. For each `#include "<file>.hfr"`, count the `varid =` occurrences in that file and insert them in order at that point. The knob's index N is its position in this combined sequence.

**Example**: MemDecodeSetup.hfr has `form` at line 25, `endform;` at line 227. There are 18 `varid =` occurrences in the form. `PerfIsoModeEn` is the 9th → position = 9/18 × 100 = 50% → lower-middle of the page.

### Position Labels

| Range | Label |
|-------|-------|
| 0–25% | Near the top of the page |
| 25–50% | In the upper-middle of the page |
| 50–75% | In the lower-middle of the page |
| 75–100% | Near the bottom of the page |

## Step 6: Trace the Full Navigation Path

Build the complete menu navigation path from the formset root down to the knob. This is the path a user would follow in the BIOS setup UI to reach the knob.

### How to trace

Starting from the form that contains the knob (found in Step 2), trace upward through `goto` references:

1. **Find which form links to this form.** Search VFR/HFR files for `goto <this_form_id>` or `goto VFR_FORMID_...` that points to the knob's containing form. The `goto` statement's `prompt` string is the menu item text the user clicks to reach this form.

2. **Repeat upward.** For the parent form found above, search for which form has a `goto` pointing to it. Continue until you reach the root form of the formset (the form defined directly inside the `formset` block in the `.vfr` file, typically the first `form formid =` after the formset declaration).

3. **Identify the formset title.** Read the `formset ... title = STRING_TOKEN(...)` declaration in the `.vfr` file and resolve its display text from the UNI file. This is the top-level entry in the BIOS setup menu.

4. **Resolve all display strings.** For each level in the path, resolve the STRING_TOKEN to its human-readable text from UNI files.

### Path format

Build the path as a chain from top to bottom, showing both the display text and the formid macro at each level:

```
<Formset Title> → <Form Display Name> (<FORMID_MACRO>) → <Form Display Name> (<FORMID_MACRO>) → <Knob Display Name>
```

**Example:**
```
Socket Configuration → Socket Configuration (VFR_FORMID_SOCKET) → Memory Decode Configuration (VFR_FORMID_MEM_DECODE) → Performance Isolation Mode
```

If a level in the path cannot be determined (e.g., the form is reached via dynamic navigation or labels), mark it with `[?]` and note what you found.

## Output Format

Present results in two parts: a **quick-reference summary** first for at-a-glance use, then the **full details** below.

### Part 1: Quick-Reference Summary

Start with the three most important pieces of information, formatted prominently:

```
## Knob Location Report: <KnobName>

### 📍 Summary

**Navigation Path:**
<Formset Title> → <Parent Form> (<FORMID>) → <This Form> (<FORMID>) → <Knob Display Name>

**Knob String:** "<Display Text>" (STRING_TOKEN(<STR_PROMPT_ID>))

**Position on Page:** Opcode <N> of <M> — <position label> (~<XX>%)

### ⚙️ Constraints

<Constraints summary from Step 1.5>

Example:
- **Visibility:** Hidden if CpuType is NOT CPU_DMRHD
- **Interaction:** Disabled if VirtualNumaEnable equals SETUP_ENABLE OR GroupMbaMode does NOT equal GROUP_MBA_MODE_DISABLE
- *Or "None — knob is always visible and enabled."*
```

### Part 2: Full Details

Then present the complete details:

```
### Knob Definition
- **File**: <file path> (Line <N>)
- **Type**: oneof / checkbox / numeric / ...
- **Varid**: <STRUCT>.<FieldName>
- **Prompt**: STRING_TOKEN(<STR_ID>) → "<Display Text>"
- **Help**: STRING_TOKEN(<STR_ID>) → "<Help Text>"
- **Options/Range**: <list options or min/max>

### Conditional Wrappers (Detailed)
- **suppressif**: <condition details with translation>
- **grayoutif**: <condition details with translation>
- **disableif**: <condition details with translation>

*(Or "None" if the knob is unconditional)*

### Containing Form
- **Form ID**: <formid value or macro name>
- **Form Title**: STRING_TOKEN(<STR_ID>) → "<Form Display Title>"
- **Form File**: <file path> (Lines <start>–<end>)
```

If the knob appears in **multiple locations** (e.g., different platforms or formsets), report each occurrence separately with its own summary block.

## Reference

For detailed VFR syntax (all question types, conditional wrappers, option flags), consult [references/vfr-syntax.md](references/vfr-syntax.md).

# VFR Syntax Quick Reference

Reference for EDK II Visual Forms Representation (VFR) language elements relevant to locating setup knobs. Based on the [EDK II VFR Specification](https://tianocore-docs.github.io/edk2-VfrSpecification/draft/).

## Table of Contents
1. [Formset](#formset)
2. [Form](#form)
3. [Question Types (Knobs)](#question-types)
4. [Conditional Wrappers](#conditional-wrappers)
5. [String Tokens (UNI)](#string-tokens)
6. [Common Flags](#common-flags)
7. [Include Pattern](#include-pattern)

---

## Formset

Top-level container. One formset per `.vfr` file.

```
formset
  guid     = <GUID_MACRO>,
  title    = STRING_TOKEN(STR_FORMSET_TITLE),
  help     = STRING_TOKEN(STR_FORMSET_HELP),
  class    = <CLASS_ID>,
  subclass = <SUBCLASS_ID>,

  <varstore declarations>
  <form definitions>

endformset;
```

## Form

A page in the setup UI. Contains questions (knobs), subtitles, and navigation (goto).

```
form formid = <ID_OR_MACRO>,
  title = STRING_TOKEN(STR_FORM_TITLE);

  subtitle text = STRING_TOKEN(STR_SECTION_TITLE);
  subtitle text = STRING_TOKEN(STR_HORIZONTAL_LINE);

  <questions, gotos, subtitles, conditionals>

endform;
```

Key facts:
- `formid` must be unique within a formset
- `title` is the form page's header text
- Forms can `#include` `.hfr` files that inject content between `form` and `endform`

## Question Types

These are the "knobs" — interactive setup items on a form.

### oneof (Dropdown / Radio)

```
oneof varid = <STRUCT>.<Field>,
    prompt  = STRING_TOKEN(STR_PROMPT),
    help    = STRING_TOKEN(STR_HELP),
    option text = STRING_TOKEN(STR_OPT1), value = 0, flags = RESET_REQUIRED;
    option text = STRING_TOKEN(STR_OPT2), value = 1, flags = DEFAULT | RESET_REQUIRED;
endoneof;
```

### checkbox (Boolean Toggle)

```
checkbox varid = <STRUCT>.<Field>,
    prompt = STRING_TOKEN(STR_PROMPT),
    help   = STRING_TOKEN(STR_HELP),
    flags  = CHECKBOX_DEFAULT,
    default = TRUE,
endcheckbox;
```

### numeric (Number Input)

```
numeric varid = <STRUCT>.<Field>,
    prompt  = STRING_TOKEN(STR_PROMPT),
    help    = STRING_TOKEN(STR_HELP),
    flags   = DISPLAY_UINT_HEX | RESET_REQUIRED,
    minimum = 0,
    maximum = 0xFF,
    step    = 1,
endnumeric;
```

### orderedlist (Sortable Priority List)

```
orderedlist varid = <STRUCT>.<Field>,
    prompt = STRING_TOKEN(STR_PROMPT),
    help   = STRING_TOKEN(STR_HELP),
    option text = STRING_TOKEN(STR_OPT1), value = 1, flags = RESET_REQUIRED;
    option text = STRING_TOKEN(STR_OPT2), value = 2, flags = RESET_REQUIRED;
endlist;
```

### string (Text Input)

```
string varid = <STRUCT>.<Field>,
    prompt  = STRING_TOKEN(STR_PROMPT),
    help    = STRING_TOKEN(STR_HELP),
    minsize = 0,
    maxsize = 20,
endstring;
```

### goto (Navigation Link to Another Form)

```
goto <FORMID_MACRO>,
    prompt = STRING_TOKEN(STR_GOTO_PROMPT),
    help   = STRING_TOKEN(STR_GOTO_HELP);
```

Not a knob itself, but useful for tracing navigation paths between forms.

### text (Static Display)

```
text
    help = STRING_TOKEN(STR_HELP),
    text = STRING_TOKEN(STR_TEXT);
```

### subtitle (Section Header / Divider)

```
subtitle text = STRING_TOKEN(STR_SECTION_NAME);
```

## Conditional Wrappers

Knobs or groups of knobs can be wrapped in conditionals:

### suppressif — Hides item when condition is true
```
suppressif <expression>;
    <knob or knobs>
endif;
```

### grayoutif — Shows item but disables interaction
```
grayoutif <expression>;
    <knob or knobs>
endif;
```

### disableif — Removes item from form entirely
```
disableif <expression>;
    <knob or knobs>
endif;
```

### Compile-time conditionals
```
#if FixedPcdGetBool(PcdSomeFeatureEnabled) == 1
    <knob definitions>
#endif
```

These use C preprocessor syntax. The knob only exists in the build if the PCD is set.

## String Tokens

String tokens are defined in `.uni` (Unicode) files:

```
#langdef en-US "English"

#string STR_FORM_TITLE          #language en-US "Memory Configuration"
#string STR_KNOB_PROMPT         #language en-US "Enforce DDR Memory Frequency POR"
#string STR_KNOB_HELP           #language en-US "Enforces Plan Of Record restrictions for DDR frequency."
#string STR_ENABLED             #language en-US "Enabled"
#string STR_DISABLED            #language en-US "Disabled"
```

Key facts:
- The `STRING_TOKEN(STR_XXX)` in VFR references `#string STR_XXX` in UNI
- Each string has a `#language` tag (usually `en-US`)
- Common shared strings: `STR_ENABLED`, `STR_DISABLED`, `STR_AUTO`, `STR_HORIZONTAL_LINE`

## Common Flags

| Flag | Meaning |
|------|---------|
| `RESET_REQUIRED` | System reboot needed when value changes |
| `INTERACTIVE` | Triggers a callback function when value changes |
| `CHECKBOX_DEFAULT` | Checkbox is checked by default |
| `DEFAULT` | This option is the default selection |
| `DISPLAY_UINT_HEX` | Display numeric value in hexadecimal |
| `DISPLAY_UINT_DEC` | Display numeric value in decimal |

## Include Pattern

Forms frequently use `#include` to pull in `.hfr` files. A typical pattern:

**In the `.vfr` file:**
```
form formid = VFR_FORMID_MEMORY,
    title = STRING_TOKEN(STR_MEMORY_CONFIG_FORM_TITLE);

    #include "MemorySetup.hfr"

endform;
```

**In `MemorySetup.hfr`:**
```
    subtitle text = STRING_TOKEN(STR_NULL_STRING);
    subtitle text = STRING_TOKEN(STR_HORIZONTAL_LINE);

    oneof varid = SOCKET_MEMORY_CONFIGURATION.EnforceDdrMemoryFreqPor,
        prompt = STRING_TOKEN(STR_ENFORCE_DDR_MEMORY_FREQ_POR_PROMPT),
        help   = STRING_TOKEN(STR_ENFORCE_DDR_MEMORY_FREQ_POR_HELP),
        option text = STRING_TOKEN(STR_POR),      value = 0, flags = RESET_REQUIRED;
        option text = STRING_TOKEN(STR_STRETCH),   value = 1, flags = RESET_REQUIRED;
        option text = STRING_TOKEN(STR_DISABLED),  value = 2, flags = RESET_REQUIRED;
    endoneof;
```

When a knob is in an `.hfr` file, the containing `form` definition is in the parent `.vfr` file — search for `#include "<hfr_filename>"` in VFR files to trace back.

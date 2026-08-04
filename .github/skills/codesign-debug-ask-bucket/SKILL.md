---
name: codesign-debug-ask-bucket
description: 'Answer a question about all failures in a vManager bucket using regex pattern search. Use when the user asks a question about a bucket (e.g. "what signals are failing in bucket X?", "what is the common error in bucket Y?"). Workflow: solve the question on a single sample failure first, then build a plan for how to use bucket pattern search to answer it across all failures, execute the plan, synthesize answer.'
argument-hint: '[bucket_name] - [your question]'
---

# Ask Bucket Skill

Answer a question that spans all failures in a vManager bucket, using filesystem artifact inspection and regex search.

This skill follows a **plan-then-execute** approach: first solve the question on one sample failure to validate the approach, then formalize the plan and run it bucket-wide.

## When to Use

- User asks a question about a specific bucket (e.g. "what signals are triggering fault in bucket X?")
- User wants to understand a pattern across many failures in one bucket
- User provides a bucket name and a question

## Prerequisites

You need:
- `project` - the vManager project (e.g. `GFC`, `NVL`)
- `bucket` - full bucket name
- `model_versions` - one or more model version tokens to filter on (e.g. `["25ww42b"]`)
- `question` - what the user wants to know

### Resolving missing prerequisites

If `bucket` or `model_versions` are not known upfront, resolve them in this order:

1. **If the user provides a sample failure path** - inspect the `*.rpt` or `*.rpt.gz` files in that directory. Both the bucket name and model version are typically embedded in the file content or its path. For example:
   ```bash
   # Look for bucket name and model version in rpt headers
   zcat <run_dir>/*.rpt.gz 2>/dev/null | head -50
   cat <run_dir>/*.rpt 2>/dev/null | head -50
   ```
   The bucket name usually appears as a `failure_cluster` or similar field, and the model version as part of the regression path (e.g. `meu-gfc-a0-master-26ww11a`) or an explicit field in the report.

2. **Otherwise** - prompt the user to provide:
   - A sample failure `run_dir` path (preferred - lets you extract both), **or**
   - The `bucket` name and `model_versions` directly

## Procedure

### Step 0 - Define the Question

Pre-processing step - classify the question before investigation begins. Do **not** attempt to answer it here.

Evaluate in order - stop at the first match:

1. **Structural ambiguity** - missing scope (no bucket/run/test), vague pronoun with no referent, multiple valid interpretations, data outside the available failure set, or too open-ended → classify as **`askquestion`**, call `#vscode/askQuestions`. Stop.
2. **Undefined technical term** - contains an acronym not defined in the available failure context. Check the architecture knowledge files in context first (Path A): if found there → **`no_clarification`**, proceed to Step 1. If not found (Path B) → classify as **`askspec`**, call `codesign-ask-specs-and-wikis`. Stop.
3. **No trigger fired** → classify as **`no_clarification`**, proceed to Step 1.

### Step 1 - Get All Failure Paths

Call `debug-get-bucket-failure-paths` with `project`, `bucket`, and `model_versions`.  
Save the **full returned list** - you will need it in Step 5.  
Take **only the first path** from the list as your sample for manual inspection (Steps 2–3).  
If the user explicitly provided a sample failure path, use that and skip this step (but you still need the full path list for Step 5 - fetch it before proceeding).

### Step 2 - Solve the Question for the Sample Failure

Your goal in this step is to **fully answer the question for the single sample failure** by hand, and in doing so discover exactly which files and patterns will be needed to answer it at scale.

### Step 3 - Translate the Sample Solution Into Patterns

Using the exact lines that answered the question in Step 2, define one or more `RegexPattern` objects:
- `description`: short label for what it captures (becomes the key in output), e.g. `"fault_signal"`
- `pattern`: regex derived from those lines, e.g. `r"FAULT: signal = (\S+)"`
- `file_glob`: glob targeting the file(s) you read in Step 2, e.g. `"**/*.rpt.gz"`

**Rules:**
- Every pattern and `file_glob` must come from lines you literally read in Step 2 - no guessing from domain knowledge
- For gzipped files, include the `.gz` extension in `file_glob` (e.g. `**/*.log.gz`) - the tool runs `zgrep -P` automatically, no decompression needed
- Be as specific as possible with `file_glob` to avoid noise

Validate by running grep against the sample - the output must be sufficient to answer the question for that one run. If not, go back to Step 2.

### Step 4 - Build the Bucket-Wide Plan

Before running anything bucket-wide, write out a concise plan that documents:

1. **Sample answer** - what you found from the sample failure and the answer it gives to the question
2. **Files targeted** - which file glob(s) you will search (e.g. `**/*.rpt.gz`) and why
3. **Patterns** - each `RegexPattern` with its `description`, `pattern`, and `file_glob`, and a one-line explanation of what it captures
4. **Expected output** - what you expect to aggregate from the results (e.g. "dominant signal name", "histogram of error codes")
5. **Answer strategy** - the Python aggregation logic you will run locally to turn raw matches into a final answer (e.g. "use `Counter` on `groups[0]`, print top-10 values")

Present this plan in a short structured block **before calling any bucket-wide tool**. This makes the approach reviewable and ensures the patterns are logically connected to the question.

### Step 5 - Run Pattern Search Across the Whole Bucket

Call `codesign-debug-search-bucket-patterns` with:
- `bucket`
- `failure_paths`: the **full list** of paths returned by `debug-get-bucket-failure-paths` in Step 1
- `patterns`: your derived list of `RegexPattern` objects

The tool runs all patterns locally over all failure paths and writes results to a JSON file.

### Step 6 - Analyze the Output File Locally

The output file is local, so analyze it by running Python directly. Do **not** load the entire file into context - it can be very large (hundreds of MB for big buckets). Instead, write a focused Python script and run it locally to produce only the aggregated result.

The JSON structure is:

```python
{
    "bucket": str,
    "total_run_dirs": int,
    "patterns": [...],
    "results": {
        "<run_dir>": {
            "<pattern_description>": [
                {"line": str, "groups": [str, ...]}
            ]
        }
    },
    "failures": [
        {"path": str, "error": str}
    ],
    "file_errors": [
        {"path": str, "error": str}
    ]
}
```

Each match entry has:
- `line` - the full matching line (context for display)
- `groups` - captured group values from the regex. Use these for aggregation - no re-parsing needed.

The `failures` list contains run_dir paths that could not be searched at all (e.g. directory not found). The `file_errors` list contains individual files within a run_dir that failed (e.g. corrupt `.gz`, grep crash) - partial results from other files in that run_dir are still preserved. Always check both lists before synthesizing the answer - if entries are present, note them and consider whether they affect the conclusion.

**Example** - count the top captured values for `fault_signal`:

```python
import json
from collections import Counter

with open("<output_file>") as f:
    data = json.load(f)

counter = Counter()
for matches in data['results'].values():
    for m in matches.get('fault_signal', []):
        if m['groups']:
            counter[m['groups'][0]] += 1

print(f"Total run dirs: {data['total_run_dirs']}")
print(f"Paths with errors: {len(data['failures'])}")
if data['failures']:
    for f in data['failures'][:5]:
        print(f"  {f['path']}: {f['error']}")
print(f"File-level errors: {len(data['file_errors'])}")
if data['file_errors']:
    for f in data['file_errors'][:5]:
        print(f"  {f['path']}: {f['error']}")

print("\nTop fault signals:")
for signal, count in counter.most_common(10):
    print(f"  {signal}: {count}")
```

Run this script locally (e.g. via shell) and capture its output.

### Step 7 - Synthesize the Answer

Use the output of the local analysis script to present a clear, concise answer to the user's question with supporting evidence.

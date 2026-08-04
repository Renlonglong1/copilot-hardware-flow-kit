---
name: bios-ras-test
description: 'End-to-end Intel RAS test workflow: generate RAK test scripts, deploy/run them on a remote debug machine, and analyze result logs. Use when the user wants to go from a RAS test scenario all the way to results — including generating a RAK Python script (memory CE/UE, PCIe AER, UPI, SDDC, ADDDC, sparing, patrol scrub, eDPC, PPR, CSMI thresholding, EINJ, CScripts injection) AND validating it by running on a remote machine AND analyzing logs. Trigger phrases: "generate and run", "create and validate", "end-to-end RAS test", "full RAS workflow", "write and execute RAK case", "run a new RAS case", "RAS test end to end", "OKS/BHS/EGS test from scratch to results". Sub-skills: rak-testscript-generator (script generation), rak-remote-runner (remote execution), rak-log-analyzer (log analysis).'
argument-hint: 'Describe the RAS test scenario, OR provide an existing .py script to run directly. Specify platform (OKS/BHS/EGS) if known.'
---

# RAS Test — End-to-End Workflow

This is an orchestration skill. It coordinates two sub-skills in sequence to take a RAS test
scenario from description (or existing script) all the way to execution results on a remote
debug machine.

## Sub-skill References

Before starting either phase, load the corresponding sub-skill file:

| Sub-skill | File | Phase |
|---|---|---|
| rak-testscript-generator | [SKILL.md](./rak-testscript-generator/SKILL.md) | Phase 1 — Script Generation |
| rak-remote-runner | [SKILL.md](./rak-remote-runner/SKILL.md) | Phase 2 — Deploy & Run |
| rak-log-analyzer | [SKILL.md](./rak-log-analyzer/SKILL.md) | Phase 3 — Log Analysis |

Read the sub-skill SKILL.md **at the start of each phase** to get full instructions, API references, and procedural rules.

User-facing documents in this folder, such as `README.txt` and `QUICKSTART.txt`, are for human users only.
They are not part of the skill execution flow and do not need to be reviewed during Phase 1, Phase 2, or Phase 3.

```
[User describes scenario or provides script]
          │
          ▼
  ┌───────────────────────┐
  │  Phase 1: GENERATE    │  ← Sub-skill: rak-testscript-generator
  │  RAK Python Script    │    (skip if user already has a script)
  └──────────┬────────────┘
             │
             ▼
  ┌───────────────────────┐
  │  Phase 2: DEPLOY &    │  ← Sub-skill: rak-remote-runner
  │  RUN on remote machine│
  └──────────┬────────────┘
             │
             ▼
  ┌───────────────────────┐
  │  Phase 3: ANALYZE     │  ← Sub-skill: rak-log-analyzer
  │  Result Logs          │    (can also be invoked standalone)
  └──────────┬────────────┘
             │
             ▼
  [Present PASS/FAIL verdict and evidence summary]
```

---

## Phase 1 — Script Generation

**Load and follow the `rak-testscript-generator` skill** for this phase.

When Phase 1 produces a new `.py` case, save it to the directory defined by
`generated_testscripts_dir` in `rak_remote_config.ini`.
If `generated_testscripts_dir` is missing, fall back to the workspace `generated_testscripts_dir/`.

Invoke it when:
- The user describes a RAS test scenario in natural language
- The user provides a recipe, IVG excerpt, or pseudo-code to convert
- The user asks to review/fix an existing script before running
- The user wants to derive a next-generation platform case from an existing case (Mode E)

Skip to Phase 2 when:
- The user already has a final `.py` RAK script and just wants to run it

Key rules enforced in this phase (see `rak-testscript-generator` for full details):
- Always ask for platform family (OKS / BHS / EGS) if not specified
- Never invent APIs, BIOS knobs, or CScripts commands not grounded in references
- Output must be a single, directly executable RAK Python script

**Remote execution and iteration are opt-in only (all modes):**
- After generating a case, do NOT auto-invoke Phase 2. Only proceed to Phase 2 when the
  user explicitly requests remote verification (e.g., "run it remotely").
- Remote iteration (run → analyze → refine → re-run) only activates when the user explicitly
  requests iterative optimization (e.g., "iterate with remote logs")
- For cross-platform case derivation, count one complete derivation only when the case is run on the remote host, logs are analyzed, and the case is updated from that evidence.
- If the user only asks to generate/derive/transform a case, output the script and stop.

---

## Phase 2 — Remote Deployment and Execution

**Load and follow the `rak-remote-runner` skill** for this phase.

Phase 2 is invoked only when:
- The user explicitly asks to run a script on the remote machine, OR
- The user explicitly requests remote iteration during Phase 1

After Phase 1 produces (or the user provides) a `.py` test script:

1. Confirm the script is saved to disk in the workspace (save it if not yet saved)
  - For cases generated in Phase 1, save under `generated_testscripts_dir` from
    `rak_remote_config.ini`.
2. Collect remote connection details (reuse from session memory if available):
   - `remote_host`, `remote_user`
   - `remote_password` should be prompted at execution time (do not store in config)
   - `remote_rak_path` (where `rak_cui.exe` lives)
   - `remote_case_dir` (upload destination)
  - `rak_result_dir` (default: `./rak_results`)
  - `generated_testscripts_dir` (local folder for Phase 1 generated cases)
  - `case_file` local path must be provided by the user at invocation time (do not put it in config)
3. Deploy and run using the `rak-remote-runner` procedure
4. Download result logs to `rak_result_dir`
5. Report: log path, exit code, elapsed time

After Phase 2 completes, always ask:
> "Logs downloaded to `<rak_result_dir>`. Do you want me to analyze the results now?"

---

## Phase 3 — Log Analysis

**Load and follow the `rak-log-analyzer` skill** for this phase.

Invoke it when:
- Phase 2 has completed and logs are available locally
- The user asks to analyze an existing RAK log package (standalone)
- The user wants to know if the test passed or failed

The log folder from Phase 2 is: `<rak_result_dir>\<case_name>\`

Pass this path directly to `rak-log-analyzer` — no need to ask the user again.

---

## Orchestration Decision Logic

| User Input | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| "Generate and run a memory CE test for OKS" | Run (generate) | Run (user said "run") | Ask if user wants analysis |
| "Here's my script, run it on the debug machine" | Skip | Run (user said "run") | Ask if user wants analysis |
| "Write a RAK case for BHS SDDC" | Run (generate only) | Skip (user did not request) | — |
| "Run the last generated script again" | Skip | Run (user said "run") | Ask if user wants analysis |
| "Review this script then run it" | Run (review mode) | Run after user confirms fixes | Ask if user wants analysis |
| "Derive OKS case from this BHS case" | Run (Mode E, static derivation) | Skip (user did not request) | — |
| "Generate OKS CE case and run it remotely" | Run (generate) | Run (user said "run remotely") | Ask if user wants analysis |
| "Derive OKS from BHS and iterate with remote logs" | Run (Mode E + remote iteration) | Run (up to 3 iterations) | Ask if user wants analysis |
| "Analyze the rak log at ./rak_results/..." | Skip | Skip | Run (analyze) |
| "Did the test pass?" | Skip | Skip | Run (analyze latest logs) |

After Phase 1 completes (when user did NOT request remote execution), simply present the
generated script. Do NOT ask whether to deploy — let the user decide.

After Phase 1 completes (when user DID request remote execution or iteration), proceed to
Phase 2 directly.

---

## Session State

This skill reads and writes `/memories/session/rak-remote-config.md` (managed by
`rak-remote-runner`) to persist connection details across phases within the same conversation.

If the session memory contains saved connection details, reuse them without re-asking.

---

## Error Recovery

| Problem | Action |
|---|---|
| Platform family not specified | Ask before generating (Phase 1 gate) |
| `paramiko` not installed | Run `pip install paramiko` (use your environment's configured proxy if required) |
| SSH connection refused | Ask user to verify host/credentials and SSH service status |
| `rak_cui.exe` not found | Ask user to confirm `remote_rak_path` |
| Script generation blocked (missing info) | Ask the 3 required clarifying questions, then proceed |
| Log folder not found after Phase 2 | Ask user to confirm `rak_result_dir` path |
| Log files missing or empty | Report which files are absent; analyze what is available |

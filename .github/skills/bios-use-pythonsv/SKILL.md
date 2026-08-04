---
name: bios-use-pythonsv
description: "Execute PythonSV commands interactively in the Copilot Chat window. Initializes and maintains a persistent PythonSV terminal session for reading/writing hardware registers via namednodes, running debug scripts, and interacting with silicon. Use this skill whenever the user wants to run PythonSV commands, access namednodes registers, read or write hardware registers, execute debug scripts like server_ip_debug or dmr_address_translator, search registers, show register fields, or perform any interactive PythonSV operation. Trigger phrases include: run pythonsv, read register, write register, namednodes, show pmon, search register, execute pythonsv, pythonsv command, start pythonsv, initialize pythonsv, dat main, server_ip_debug."
---

# PythonSV Interactive Executor

Execute PythonSV commands in a persistent terminal session directly from the Copilot Chat window. This skill manages the full lifecycle: initializing the PythonSV environment, maintaining the session, executing user commands, and displaying results.

## Why This Skill Exists

PythonSV is the primary interface for interacting with Intel silicon — reading registers, running debug flows, and executing platform scripts. Engineers frequently need to run commands and see results without leaving their editor. This skill bridges that gap by maintaining a live PythonSV session and piping commands through it.

## Core Workflow

### Phase 1: Environment Setup (First Invocation)

On the very first call in a conversation, you need to establish the PythonSV execution context.

1. **Check for saved configuration**: Read `references/platform_config.json` (in this skill's directory) to see if the user has previously saved their platform paths.

2. **If config exists**, present the saved settings and ask the user to confirm:
   - PythonSV directory path
   - Python interpreter (venv) path
   - Start script and arguments
   
   Use `vscode_askQuestions` to let them confirm or modify.

3. **If no config exists**, ask the user to provide:
   - **Platform name** (e.g., SPR, EMR, GNR, DMR)
   - **PythonSV directory** — the directory containing the start script (e.g., `C:\pythonsv\diamondrapids`)
   - **Python venv interpreter path** — the full path to `python.exe` in the platform's virtual environment (e.g., `C:\pythonsv.venv\diamondrapids_python3.10\Scripts\python.exe`)
   - **Start script** — the script filename and any arguments (e.g., `startdmr.py -a ipc -p DMR`)
   
   After the user confirms, save the config to `references/platform_config.json`.

4. **Initialize the terminal session**:
   - Use `run_in_terminal` with `mode=async` to start the PythonSV session
   - First `cd` into the PythonSV directory
   - Then execute the Python interpreter with the start script
   - Wait for the IPython prompt to appear (look for `In [` or `>>>` in the output)
   - This terminal session ID is your persistent context — reuse it for all subsequent commands

**Example initialization sequence:**
```
cd C:\pythonsv\diamondrapids
C:\pythonsv.venv\diamondrapids_python3.10\Scripts\python.exe startdmr.py -a ipc -p DMR
```

### Phase 2: Command Execution (Ongoing)

Once the PythonSV session is alive, execute user commands in the same terminal:

1. **Parse the user's intent** — they might say things like:
   - "Read register X on socket0.cbb0" → translate to the appropriate namednodes command
   - "Search for register foo" → `namednodes.sv.socket0.search("foo")`
   - "Show me the fields of register bar" → `namednodes.sv.socket0.<path>.bar.show()`
   - Or they might give you a raw Python command to execute directly

2. **Send the command** using `send_to_terminal` with the saved terminal ID

3. **Retrieve and display the output** using `get_terminal_output` — show the full output in the chat window so the user can see the results immediately

4. **If the output is very long**, present it in a fenced code block so the chat window provides scrolling.

### Phase 3: Session Management

- **Maintain context**: All commands go to the same terminal session. Do NOT create new terminals unless the user explicitly asks to reinitialize.
- **Re-initialization**: If the user says "restart pythonsv" or "reinitialize", kill the old terminal and start a new session from Phase 1 Step 4.
- **Session loss detection**: If `send_to_terminal` or `get_terminal_output` fails, inform the user that the session may have been lost and offer to reinitialize.

## Platform Configuration Reference

Known platform patterns (paths vary by user environment):

| Platform | Start Script Pattern | Typical Arguments |
|----------|---------------------|-------------------|
| SPR (Sapphire Rapids) | `startspr.py` | (none) |
| EMR (Emerald Rapids) | `startemr.py` | (none) |
| GNR (Granite Rapids) | `startgnr.py` | `-a ipc -p GNR` |
| DMR (Diamond Rapids) | `startdmr.py` | `-a ipc -p DMR` |

These are examples only — always confirm actual paths with the user.

## Config File Format

Save to `references/platform_config.json`:

```json
{
  "platform": "DMR",
  "pythonsv_directory": "C:\\pythonsv\\diamondrapids",
  "python_interpreter": "C:\\pythonsv.venv\\diamondrapids_python3.10\\Scripts\\python.exe",
  "start_script": "startdmr.py",
  "start_args": "-a ipc -p DMR"
}
```

## Command Translation Guide

When a user describes what they want in natural language, translate to the appropriate PythonSV command. The workspace's `copilot-instructions.md` contains the full namednodes API reference — consult it for the correct syntax. Common patterns:

| User says | PythonSV command |
|-----------|-----------------|
| "Read register X at path Y" | `namednodes.sv.socket0.Y.X.read()` |
| "Write 0x1 to register X" | `namednodes.sv.socket0.Y.X.write(0x1)` |
| "Show fields of register X" | `namednodes.sv.socket0.Y.X.show()` |
| "Search for register foo" | `namednodes.sv.socket0.search("foo")` |
| "Search field bar in cbb0" | `namednodes.sv.socket0.cbb0.search("bar", "f")` |
| "Run DAT" | `import diamondrapids.mc.dmr_address_translator as dat; dat.main()` |
| "Show PMONs for sca" | `from pysvtools import server_ip_debug; server_ip_debug.sca.pmon.show_pmons()` |

If you're unsure how to translate, just ask the user, or execute their command verbatim if it looks like valid Python.

## Displaying Output

- Always show the terminal output back to the user in the chat window
- For short outputs (< 30 lines), display inline in a fenced code block
- For long outputs, still use a fenced code block — the chat window will provide scrolling automatically
- If the command produces an error, show the full traceback and offer diagnosis

### Extracting Relevant Output

`get_terminal_output` returns the **entire terminal buffer**, including startup logs. To show the user only the output from their latest command:

1. Look for the most recent `In [N]:` prompt with the command that was just sent
2. Extract everything from that line through the next `In [N+1]:` prompt (or end of output)
3. Present only this relevant portion to the user — do NOT dump the entire startup log every time

For example, if the terminal shows a long startup log followed by:
```
In [2]: namednodes.sv.socket0.cbb0.search("err")
socket0.cbb0.base.err_status ...
In [3]:
```
Show only the search results between `In [2]:` and `In [3]:`.

## Handling Long-Running Commands

Some PythonSV operations can take a long time:

- **Full socket search** (`socket0.search(...)`) traverses the entire hierarchy — can take minutes on multi-socket DMR systems
- **Broad register reads** across many components
- **Discovery** during initialization

When a command is taking a long time:
1. Inform the user that the operation is still running
2. Suggest scoping the search narrower if applicable (e.g., `socket0.cbb0.search(...)` instead of `socket0.search(...)`)
3. Continue checking `get_terminal_output` periodically until the next `In [N]:` prompt appears
4. Do NOT re-send the command — just wait for it to complete

## Session State Tracking

Use session memory (`/memories/session/`) to persist:
- The terminal session ID (so you can reuse it across turns)
- The platform config that was confirmed
- Whether initialization is complete

This way, if the conversation continues, you know exactly where you left off.

## Important Notes

- **Never guess register paths.** If you're not sure about a register's location in the hierarchy, use the search function first, but prefer scoped searches (e.g., `socket0.cbb0.search(...)`) over full socket searches to avoid long waits.
- **The PythonSV session is stateful.** Variables defined in earlier commands persist. Import statements persist. This is by design — the user builds up state over the course of a debug session.
- **Do not create a new terminal for each command.** The whole point is maintaining a single persistent session.
- **If the user provides raw Python code**, execute it as-is without modification.
- **If initialization takes a long time**, reassure the user that PythonSV startup can take a while (especially when discovering hardware) and check the terminal output periodically.
- **Venv paths vary.** The Python venv directory might be `.venv`, `venv`, or a completely custom path. Always confirm with the user — do not assume.

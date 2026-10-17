# Claude Code CLI Contract & Interface Specification

**Verified Binary Version:** `2.1.296 (Claude Code)`  
**Platform:** Native Windows (`AMD64`) / PowerShell / cmd.exe / Git Bash  
**Last Verified Date:** 2026-10-14  

---

## 1. Verified CLI Commands, Flags, and Arguments

Derived directly from `claude --help` and live execution tests of `claude` (v2.1.296).

### 1.1 Invocation Syntax
```bash
claude [options] [command] [prompt]
```

### 1.2 Core Execution & Mode Options
| Option | Arguments | Description & Verified Behavior |
|---|---|---|
| `-p, --print` | none | Non-interactive headless mode. Prints output and exits. Workspace trust dialog is skipped automatically. |
| `--output-format` | `text`, `json`, `stream-json` | Output formatting. When `--print` is active: <br>- `text`: raw assistant text (default)<br>- `json`: single JSON summary object with `result`, `usage`, `total_cost_usd`, `num_turns`<br>- `stream-json`: newline-delimited JSON stream of events (`message_start`, `content_block_start`, `content_block_delta`, `message_delta`, `message_stop`, hook events). |
| `--input-format` | `text`, `stream-json` | Input stream handling with `--print`. `stream-json` allows piped bidirectional multi-turn sessions. |
| `--model` | `<model>` | Target model alias (`sonnet`, `haiku`, `opus`, `fable`) or exact canonical model ID. |
| `--fallback-model` | `<model>` | Comma-separated list of fallback models tried in sequence when primary is overloaded/fails. |
| `--effort` | `low`, `medium`, `high`, `xhigh`, `max` | Controls reasoning/thinking depth effort level. |
| `--max-budget-usd` | `<amount>` | Spend ceiling in USD for API calls (only works with `--print`). |

### 1.3 Tools & Permissions
| Option | Arguments | Description & Verified Behavior |
|---|---|---|
| `--allowedTools, --allowed-tools` | `<tools...>` | Space/comma separated list of tools allowed without prompting (e.g. `Write Edit Read Bash Glob Grep Task Skill`). |
| `--disallowedTools, --disallowed-tools` | `<tools...>` | Tools explicitly forbidden. |
| `--tools` | `<tools...>` | Set available tools: `""` disables all, `"default"` uses standard set, or comma-separated names. |
| `--permission-mode` | `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan` | Policy for interactive tool approval. `dontAsk` or `bypassPermissions` used in sandboxes. |
| `--permission-prompts` | `host`, `none` | Who handles permission prompts in print mode (`none` auto-denies anything that would prompt). |
| `--dangerously-skip-permissions` | none | Complete bypass of all permission prompts. Intended solely for isolated sandboxes. |
| `--allow-dangerously-skip-permissions` | none | Permits enabling permission skip without making it the default. |

### 1.4 Sandboxing, Customization & Extensions
| Option | Arguments | Description & Verified Behavior |
|---|---|---|
| `--add-dir` | `<dirs...>` | Whitelist additional directory paths for tool access. |
| `--mcp-config` | `<configs...>` | JSON files or JSON strings defining Model Context Protocol (MCP) servers (stdio & SSE/HTTP). |
| `--strict-mcp-config` | none | Ignore global/project MCP configurations; use only `--mcp-config`. |
| `--plugin-dir` | `<path>` | Load plugin from directory or zip for this session only (repeatable). |
| `--plugin-url` | `<url>` | Fetch and load plugin zip from URL for session. |
| `--safe-mode` | none | Disables all CLAUDE.md, skills, plugins, hooks, MCP servers, and custom commands. Sets `CLAUDE_CODE_SAFE_MODE=1`. |
| `--bare` | none | Minimal mode: skips hooks, LSP, plugin sync, attribution, auto-memory, CLAUDE.md discovery. Sets `CLAUDE_CODE_SIMPLE=1`. |
| `--disable-slash-commands` | none | Disables all slash commands and skills. |

### 1.5 Session Management & Telemetry
| Option | Arguments | Description & Verified Behavior |
|---|---|---|
| `--session-id` | `<uuid>` | Pin specific UUID for conversation session. |
| `-c, --continue` | none | Continue most recent session in current working directory. |
| `-r, --resume` | `[id]` | Resume specific session by ID or launch interactive picker. |
| `--fork-session` | none | Resumes conversation while branching to a fresh session ID. |
| `--no-session-persistence` | none | Keep session entirely in memory without writing to disk. |
| `--system-prompt` | `<prompt>` | Complete override for system prompt. |
| `--append-system-prompt` | `<prompt>` | Append text to default system prompt. |
| `--include-hook-events` | none | Emits hook lifecycle events into `stream-json`. |
| `--include-partial-messages` | none | Streams raw token deltas as they arrive in `stream-json`. |
| `-d, --debug` | `[filter]` | Detailed debug logging to stderr with optional category filters. |
| `--debug-file` | `<path>` | Writes debug logs to disk. |

---

## 2. Environment Variables Contract

Claude Code respects the following environment variables, evaluated in order of precedence:

| Variable | Scope | Purpose & Rules |
|---|---|---|
| `ANTHROPIC_BASE_URL` | Network | Points Claude Code to claude-master gateway (e.g. `http://127.0.0.1:8080` or ephemeral test port). |
| `ANTHROPIC_API_KEY` | Auth | Upstream API key or `"dummy"` when the gateway manages keys via key pools. |
| `ANTHROPIC_AUTH_TOKEN` | Auth | Overrides `ANTHROPIC_API_KEY` if set. Must be unset in sandboxes to prevent leaking ambient keys. |
| `ANTHROPIC_MODEL` | Routing | Default model alias if `--model` flag is not passed. |
| `CLAUDE_CONFIG_DIR` | Storage | Root folder for settings, transcripts, history, and project state. **Mandatory for sandboxing**: each test run must use an isolated temporary config dir to protect user state. |
| `CLAUDE_CODE_SAFE_MODE` | Runtime | Set to `1` by `--safe-mode`. Disables external customizations. |
| `CLAUDE_CODE_SIMPLE` | Runtime | Set to `1` by `--bare`. Bypasses hooks, LSP, and memory. |
| `FORCE_COLOR` / `NO_COLOR` | Output | Controls ANSI escape sequence emission in terminal drivers. |

---

## 3. The Two Mandatory Test Drivers

### 3.1 Headless Driver (`claude -p`)
- **Invocation**: `claude -p "<prompt>" --output-format json [options]` or `--output-format stream-json`.
- **Isolation**:
  1. Fresh temporary working directory (`tempfile.mkdtemp`), initialized with `git init`.
  2. Isolated `CLAUDE_CONFIG_DIR` with custom `settings.json` routing to local gateway port.
  3. Cleaned environment (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY="dummy"`, ambient auth tokens removed).
- **Event Extraction**: Parses structured JSON result:
  - `result`: Text response from Claude Code.
  - `usage`: Input/output tokens and prompt cache stats.
  - `num_turns`: Count of tool execution turns.
  - `total_cost_usd`: CLI-reported spend.
- **Correlation**: Every request sent to the gateway is correlated by `X-Request-Id` and SHA digest with gateway trace logs.

### 3.2 Interactive TUI Driver (Windows ConPTY)
- **Mechanism**: Spawns `claude` (without `-p`) inside a true native Windows Pseudo Console (`CreatePseudoConsole` via `pywin32` / `ctypes` or `winpty`).
- **Input**: Sends raw VT100 keystrokes and newline sequences into the ConPTY input pipe.
- **Output & Screen Scraping**: Reads ConPTY output pipe in real time, strips/interprets ANSI escape sequences into a screen buffer.
- **State-Based Waits (No Sleep Loops)**:
  - Wait for ready prompt (`>` or `?` or box drawing prompt glyph).
  - Wait for streaming completion (terminal idle + prompt re-appearance).
  - Wait for modal dialogs (permission prompt, approval question).
  - Timeout protection: Hard wall-clock timeout with process-tree kill (`taskkill /F /T /PID`).

---

## 4. Independent Oracles

No model output text ("I have created the file", "Tests passed") is ever accepted as truth. All scenarios must be verified by independent oracles:
1. **Filesystem Oracle**: Verifies files exist on disk, matching expected size, SHA256 hashes, AST parse, or exact contents.
2. **Execution Oracle**: Directly executes generated code or test suites (`python check.py`, `pytest`, compiler exit codes) in the sandbox.
3. **Git Oracle**: Verifies `git status`, `git log`, commit messages, diffs, and branch states.
4. **Gateway Telemetry Oracle**: Queries gateway trace logs for request counts, token usage, model route selected, upstream HTTP status codes, and latency.
5. **Hook/Brain Oracle**: Inspects SQLite database in brain (`episodic_events`, `brain_nodes`) and hookshim logs to verify interception events occurred.

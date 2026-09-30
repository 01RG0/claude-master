# Claude Code Facts

> Summary of verified facts about the Claude Code binary hooks interface.  
> Source: Official docs at https://code.claude.com/docs/en/hooks.md + binary inspection (2026-09-30)  
> Binary version: 2.1.263+ (confirmed from `/home/rootuser/.claude.json`)

---

## Hook System Overview

- Hooks are **user-defined handlers** that run automatically at specific lifecycle points
- Three handler delivery mechanisms: **command** (stdin/stdout), **HTTP** (POST body/response), **MCP tool**
- Two advanced types: **prompt** (single-turn LLM eval) and **agent** (subagent with tools)
- All matching hooks in a group run **in parallel**
- Configuration lives in `~/.claude/settings.json` or `.claude/settings.json`

## Confirmed Hook Events (Core Four)

| Event | When | Can Block? | Cadence |
|---|---|---|---|
| `UserPromptSubmit` | After user submits prompt, before Claude processes | Yes (exit 2) | Per-turn |
| `PreToolUse` | Before any tool call executes | Yes (exit 2) | Per-tool-call |
| `PostToolUse` | After tool call succeeds | No | Per-tool-call |
| `Stop` | When Claude finishes responding | No (exit 2 ignored) | Per-turn |

## Full Event List (27 total)

Per-session: `SessionStart`, `Setup`, `SessionEnd`  
Per-turn: `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure`  
Per-tool: `PreToolUse`, `PermissionRequest`, `PermissionDenied`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`  
Async/standalone: `Notification`, `MessageDisplay`, `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `Elicitation`, `ElicitationResult`

## stdin JSON: Common Fields

Every hook event receives on stdin:
- `session_id` — session identifier
- `prompt_id` — UUID for current prompt (v2.1.196+)
- `transcript_path` — path to JSONL transcript
- `cwd` — current working directory
- `scratchpad_dir` — temp working dir (v2.1.257+)
- `permission_mode` — `"default"`, `"plan"`, `"acceptEdits"`, `"auto"`, `"dontAsk"`, `"bypassPermissions"`
- `effort` — `{ "level": "low"|"medium"|"high"|"xhigh"|"max" }`
- `hook_event_name` — event name string

Tool events additionally include: `tool_name`, `tool_input`, `tool_use_id`  
PostToolUse additionally includes: `tool_response`  
Stop additionally includes: `last_assistant_message`, `stop_hook_active`  
Subagent contexts additionally include: `agent_id`, `agent_type`

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success — proceed; JSON output (if any) is processed |
| 2 | Block — halts execution for gating events only |
| Other | Non-blocking error — logged, execution continues |

**Gating events** (exit 2 blocks): `PreToolUse`, `PermissionRequest`, `UserPromptSubmit`, `UserPromptExpansion`  
**Non-gating events** (exit 2 ignored): `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd`, all async events

## Context Injection

- **Primary mechanism**: `UserPromptSubmit` hook stdout (plain text or JSON with `systemMessage`)  
- **Universal mechanism**: `systemMessage` field in JSON output — delivered as system reminder to Claude  
- The `systemMessage` field in stdout JSON is the canonical way for the brain shim to inject retrieved memories

## stdout JSON Output

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Reason shown to Claude"
  },
  "systemMessage": "Optional context injected as system reminder",
  "continue": true,
  "stopReason": "Optional message if continue=false"
}
```

## CLI Flags Related to Hooks

- `--bare` — skips hooks entirely (minimal mode)
- `--include-hook-events` — includes hook lifecycle events in `--output-format=stream-json` output
- `/hooks` command inside a session — read-only browser for configured hooks

## Settings Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/shim",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Current `~/.claude/settings.json` on this machine: `{ "theme": "dark" }` (no hooks configured yet)

## MCP Tool Naming Pattern

MCP tools follow: `mcp__<server>__<tool>`  
- Example: `mcp__memory__create_entities`, `mcp__filesystem__read_file`  
- Plugin-bundled: `mcp__plugin_<plugin-name>_<server-name>__<tool>`

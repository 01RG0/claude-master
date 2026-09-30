# Hook Payloads Contract

> Source: https://code.claude.com/docs/en/hooks.md (fetched 2026-09-30)
> Binary: `/home/rootuser/.local/bin/claude` (version 2.1.263+, confirmed via `--include-hook-events` flag)

---

## Verified Hook Event Names

The following events are confirmed from the official Claude Code hooks reference:

### Per-session events
- `SessionStart` — fires when a session begins or resumes
- `SessionEnd` — fires when a session terminates
- `Setup` — fires with `--init-only`, `--init`, or `--maintenance` in `-p` mode

### Per-turn events
- `UserPromptSubmit` — fires when user submits a prompt, before Claude processes it ✅ VERIFIED
- `UserPromptExpansion` — fires when a slash command expands to a prompt
- `Stop` — fires when Claude finishes responding ✅ VERIFIED
- `StopFailure` — fires when turn ends due to API error

### Per-tool-call events (agentic loop)
- `PreToolUse` — fires before a tool call executes; **can block** ✅ VERIFIED
- `PostToolUse` — fires after a tool call succeeds ✅ VERIFIED
- `PostToolUseFailure` — fires after a tool call fails
- `PermissionRequest` — fires when a tool call needs a permission decision
- `PermissionDenied` — fires when auto mode denies a tool call
- `PostToolBatch` — fires after a full batch of parallel tool calls resolves

### Other events (confirmed from docs)
- `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`
- `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`
- `TeammateIdle`, `Notification`, `MessageDisplay`
- `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`
- `WorktreeCreate`, `WorktreeRemove`
- `Elicitation`, `ElicitationResult`

> **Note on `Stop`**: The docs confirm `Stop` fires when Claude finishes responding (per-turn). The shim should hook `Stop` for post-turn brain writes.

---

## Common Input Fields (stdin JSON)

All hook events receive these common fields on **stdin** (command hooks) or as the **POST body** (HTTP hooks):

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Current session identifier |
| `prompt_id` | string (UUID) | Identifies the current user prompt being processed. Absent until first user input. Requires v2.1.196+ |
| `transcript_path` | string | Path to conversation JSONL transcript file |
| `cwd` | string | Current working directory when hook is invoked |
| `scratchpad_dir` | string | Path to session scratchpad directory. Absent when unavailable. Requires v2.1.257+ |
| `permission_mode` | string | One of: `"default"`, `"plan"`, `"acceptEdits"`, `"auto"`, `"dontAsk"`, `"bypassPermissions"` |
| `effort` | object | `{ "level": "low"|"medium"|"high"|"xhigh"|"max" }`. Present for tool-use events on supported models |
| `hook_event_name` | string | Name of the event that fired |
| `agent_id` | string | (subagent only) Unique identifier for the subagent |
| `agent_type` | string | (subagent only) Agent type name, e.g. `"Explore"`, `"security-reviewer"` |

---

## Event-Specific Input Fields

### `UserPromptSubmit`

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to reverse a string"
}
```

Additional fields:
| Field | Type | Description |
|---|---|---|
| `prompt` | string | The user prompt text that was submitted |

> Stdout from `UserPromptSubmit` hooks (exit 0) is shown as context Claude can see. Use this to **inject additional context** (memory, skill summaries, etc.).

### `PreToolUse`

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test",
    "description": "Run test suite",
    "timeout": 120000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01ABC123..."
}
```

Additional fields:
| Field | Type | Description |
|---|---|---|
| `tool_name` | string | Name of the tool being called (e.g., `Bash`, `Write`, `Edit`, `mcp__server__tool`) |
| `tool_input` | object | Arguments passed to the tool (shape varies by tool) |
| `tool_use_id` | string | Unique identifier for this tool call |

### `PostToolUse`

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test"
  },
  "tool_use_id": "toolu_01ABC123...",
  "tool_response": {
    "output": "All tests passed.\n",
    "error": null
  }
}
```

Additional fields (beyond `PreToolUse`):
| Field | Type | Description |
|---|---|---|
| `tool_response` | object | The result returned by the tool. Shape varies by tool |

### `Stop`

```json
{
  "session_id": "abc123",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
  "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
  "cwd": "/home/user/my-project",
  "hook_event_name": "Stop",
  "last_assistant_message": "I've completed the task. The function now correctly reverses the string.",
  "stop_hook_active": false
}
```

Additional fields:
| Field | Type | Description |
|---|---|---|
| `last_assistant_message` | string | The final assistant message text of the current turn |
| `stop_hook_active` | boolean | Whether a stop hook is already active (prevents re-entry) |

---

## Stdout JSON Output Structure

Hook handlers communicate decisions back via stdout JSON. The top-level key is `hookSpecificOutput`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Destructive command blocked by hook"
  }
}
```

### Universal Output Fields (top-level)

| Field | Type | Description |
|---|---|---|
| `continue` | boolean | If `false`, Claude stops responding and exits the agentic loop |
| `stopReason` | string | Message shown to user when `continue: false` |
| `systemMessage` | string | Text shown to Claude as system context. Most events support this |
| `terminalSequence` | string | ANSI/terminal sequences for notifications (bell, title, etc.) |

### `hookSpecificOutput` Fields by Event

#### `PreToolUse` — `hookSpecificOutput`
| Field | Type | Description |
|---|---|---|
| `hookEventName` | string | Must be `"PreToolUse"` |
| `permissionDecision` | string | One of: `"allow"`, `"deny"`, `"ask"`, `"defer"` |
| `permissionDecisionReason` | string | Human-readable reason shown to Claude when denied |

#### `PostToolUse` — `hookSpecificOutput`
| Field | Type | Description |
|---|---|---|
| `hookEventName` | string | Must be `"PostToolUse"` |
| `updatedToolOutput` | string/object | Overrides the tool result seen by the agent |

#### `UserPromptSubmit` — output behavior
- Plain text stdout (exit 0) is injected as context Claude can see
- JSON output with `systemMessage` field injects structured context
- **This is the canonical injection point for brain context** (memories, skills, etc.)

#### `Stop` — `hookSpecificOutput`
| Field | Type | Description |
|---|---|---|
| `hookEventName` | string | Must be `"Stop"` |
| (no blocking fields) | — | Stop hooks cannot block (exit 2 has no effect) |

---

## Exit Code Meanings

| Exit Code | Behavior |
|---|---|
| **0** | **Success** — proceed with the action; optional JSON output is processed |
| **2** | **Block** — stop the action (only for `PreToolUse` and events that support blocking); JSON output is still read |
| **Other (1, 3+)** | **Non-blocking error** — logged, execution continues |

### Exit Code 2 Behavior Per Event

| Event | Exit 2 Effect |
|---|---|
| `PreToolUse` | Blocks tool call; shows reason to Claude |
| `PermissionRequest` | Blocks tool call |
| `UserPromptSubmit` | Blocks prompt; prevents Claude from processing it |
| `UserPromptExpansion` | Blocks the expansion |
| `Stop` | **No effect** — exit 2 is ignored; stop hooks cannot block |
| `PostToolUse` | **No effect** — non-blocking |
| `SessionStart` | **No effect** — non-blocking |
| `SessionEnd` | **No effect** — non-blocking |

> **Key insight**: Exit 2 only blocks on events that have a "gate" (PreToolUse, UserPromptSubmit). Observational events ignore exit 2.

---

## Context Injection Field

The **canonical field for injecting additional context** into Claude's awareness is:

1. **`UserPromptSubmit` hook stdout** — plain text or JSON with `systemMessage` key. This text is prepended as context Claude sees before processing the prompt.
2. **`systemMessage`** in JSON output — works across most events; delivers a system-level reminder to Claude.

```json
{
  "systemMessage": "Relevant memory context:\n- User prefers TypeScript\n- Last worked on auth module\n- Known issue: flaky test in user.test.ts"
}
```

> `systemMessage` is the primary injection mechanism for the brain shim to deliver retrieved memories, skill summaries, and episodic context.

---

## Settings Configuration Schema

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
            "args": [],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Hook handler types: `"command"`, `"http"`, `"mcp_tool"`, `"prompt"`, `"agent"`

---

## Synthetic JSON Payload Fixtures

### Fixture 1: UserPromptSubmit

```json
{
  "session_id": "sess_01ABCDEFGHIJ",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440001",
  "transcript_path": "/home/user/.claude/projects/abc/transcript.jsonl",
  "cwd": "/home/user/claude-master",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Implement a Redis cache wrapper with TTL support"
}
```

### Fixture 2: PreToolUse (Bash)

```json
{
  "session_id": "sess_01ABCDEFGHIJ",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440002",
  "transcript_path": "/home/user/.claude/projects/abc/transcript.jsonl",
  "cwd": "/home/user/claude-master",
  "permission_mode": "auto",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push origin main --force",
    "description": "Push changes to remote",
    "timeout": 30000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01XYZ789FIXTURE",
  "effort": { "level": "medium" }
}
```

### Fixture 3: PostToolUse (Write)

```json
{
  "session_id": "sess_01ABCDEFGHIJ",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440003",
  "transcript_path": "/home/user/.claude/projects/abc/transcript.jsonl",
  "cwd": "/home/user/claude-master",
  "permission_mode": "acceptEdits",
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/home/user/claude-master/brain/memory.py",
    "content": "# Memory module\n..."
  },
  "tool_use_id": "toolu_01WRITE456FIXTURE",
  "tool_response": {
    "output": "File written successfully",
    "error": null
  },
  "effort": { "level": "high" }
}
```

### Fixture 4: Stop

```json
{
  "session_id": "sess_01ABCDEFGHIJ",
  "prompt_id": "550e8400-e29b-41d4-a716-446655440004",
  "transcript_path": "/home/user/.claude/projects/abc/transcript.jsonl",
  "cwd": "/home/user/claude-master",
  "hook_event_name": "Stop",
  "last_assistant_message": "I've implemented the Redis cache wrapper with TTL support. The implementation includes automatic expiry, cache-aside pattern, and connection pooling.",
  "stop_hook_active": false,
  "effort": { "level": "medium" }
}
```

---

## UNVERIFIED

The following could not be confirmed directly from the binary or live session inspection:

1. **`tool_response` exact shape for each tool** — the `tool_response` object structure varies by tool (Bash vs Write vs Edit vs MCP tools). Only the Bash variant is well-documented. Other tool response shapes are inferred.

2. **`prompt_id` presence on `Stop`** — the docs note it is present on events "within a tool-use context" and requires v2.1.196+; presence on `Stop` is stated in the common fields table but not shown in a Stop-specific example in the docs.

3. **`effort` on `UserPromptSubmit`** — docs say "present for events that fire within a tool-use context"; unclear if UserPromptSubmit qualifies. Omitted from Fixture 1 to be safe.

4. **`permission_mode` on `Stop`** — not shown in the Stop-specific example in the docs; uncertain if included.

5. **Exit code 2 on `UserPromptExpansion`** — documented as blocking but no concrete example shown.

6. **`updatedToolOutput` schema** — exact type (string vs object) unconfirmed for PostToolUse.

7. **Binary version on this machine** — confirmed as 2.1.263+ (from `.claude.json`). Features requiring v2.1.196+ (`prompt_id`) and v2.1.257+ (`scratchpad_dir`) should be present.

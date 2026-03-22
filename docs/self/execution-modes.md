# Execution Modes

The pipeline supports two execution modes: **API mode** (default) and **Claude Code mode**. They can be set globally or per-step.

---

## API Mode (`api`)

The default. Uses the Anthropic Python SDK (`anthropic.Anthropic().messages.create()`).

### How it works

`utils/agent.py → AgentRunner` manages a tool-use conversation loop:
1. Send a `messages.create` request with tool definitions
2. Receive tool calls from the model
3. Execute them locally (write file, read file, run tests)
4. Feed results back to the model as `tool_result` blocks
5. Repeat until the `complete` tool is called
6. Return the payload from `complete`

### Strengths
- **Precise control** — tool schemas strictly define what the agent can do
- **Structured output** — the `complete` tool enforces the exact output shape
- **Stateful retries** — the TDD Green loop keeps the full message history across attempts, so the model knows what it already tried
- **No extra installation** — only requires `anthropic` Python package

### Weaknesses
- Custom tool implementation — we maintain `write_file`, `read_file`, `run_tests` ourselves
- Token-bounded — very long conversations (many retries, large workspaces) can hit context limits
- No access to Claude Code's extended tools (Glob, Grep, multi-file Edit, etc.)

---

## Claude Code Mode (`claude_code`)

Uses the Claude Code CLI (`claude`) as a subprocess.

### How it works

`utils/claude_code_runner.py → ClaudeCodeRunner` invokes the CLI:
```bash
claude --print -p "PROMPT" --allowedTools "Write,Edit,Read,Bash,Glob,Grep" --output-format json --model claude-sonnet-4-6
```

Claude Code executes in the workspace directory (via `cwd`), using its native tools to read, write, and run code. The result comes back as JSON via stdout.

For structured-output steps, an addendum instructs the model to end its response with a `\`\`\`json` block. The runner parses this block.

For code-writing steps, an addendum replaces custom tool instructions with native Claude Code tool guidance.

### Strengths
- **Native tools** — Claude Code's built-in Write/Edit/Bash/Glob/Grep are more capable than our custom implementations
- **Bash access** — can run arbitrary shell commands in the workspace (install deps, compile, run tests) without needing our executor wrapper
- **Self-contained** — each invocation is independent; no message state to manage
- **Extended tool set** — Glob for file pattern matching, Grep for content search, multi-file Edit operations

### Weaknesses
- **Requires Claude Code CLI** — must be installed separately (`npm install -g @anthropic-ai/claude-code`)
- **Single-turn** — no persistent message history across retries; each attempt starts fresh (with full context concatenated into the prompt)
- **Less structured output** — relies on JSON block parsing, which can fail if the model doesn't format correctly
- **Harder to control** — the model has more freedom with `Bash` (e.g., could run unintended commands)

---

## Configuration

### Global default

In `pipeline.json`:
```json
{
  "execution_mode": "api"
}
```
Change to `"claude_code"` to use Claude Code for all steps.

### Per-step override

Add `"execution_mode"` to any step in `pipeline.json`:
```json
{
  "id": "tdd_green",
  "execution_mode": "claude_code",
  ...
}
```
This overrides the global default for that step only.

### CLI override

Pass `--mode` to override everything:
```bash
python runner.py "Feature" --mode claude_code
python runner.py "Feature" --mode api
```

The precedence is: **CLI flag > per-step config > global default**.

### Claude Code CLI settings

```json
{
  "claude_code": {
    "command": "claude",
    "timeout_seconds": 600,
    "code_tools": "Write,Edit,Read,Bash,Glob,Grep",
    "read_only_tools": "Read,Glob,Grep"
  }
}
```

| Field | Description |
|-------|-------------|
| `command` | Path or name of the CLI binary. Change if `claude` is not on PATH. |
| `timeout_seconds` | Max time per invocation. Code steps may need 5–10 minutes. |
| `code_tools` | Tool allowlist for code-writing steps. |
| `read_only_tools` | Tool allowlist for structured-output steps. |

---

## Recommended configuration by step

| Step | Recommended mode | Reason |
|------|-----------------|--------|
| Requirements | `api` | Structured JSON output, no file writing |
| Plan | `api` | Structured JSON output, no file writing |
| TDD Red | Either | Simple file writing; both work well |
| TDD Green | `claude_code` | Native Bash for running tests mid-session is very powerful |
| Verification | `api` | Structured JSON output |
| Integration | `claude_code` | Multi-step test writing + execution benefits from native tools |
| Post-mortem | `api` | Large structured proposal schema; more reliable with tool-use |

Example mixed-mode config:
```json
{
  "execution_mode": "api",
  "steps": [
    { "id": "tdd_green", "execution_mode": "claude_code", ... },
    { "id": "integration", "execution_mode": "claude_code", ... }
  ]
}
```

---

## Checking CLI availability

```bash
python runner.py --check-cli
```

Or directly:
```bash
claude --version
```

Install Claude Code:
```bash
npm install -g @anthropic-ai/claude-code
```

---

## Differences in TDD Green retry behaviour

### API mode
The agent maintains full message history across retry attempts:
- Attempt 1: sees test output → writes files
- Attempt 2: sees original context + attempt 1 file writes + new test output → fixes remaining failures
- This is efficient: the model doesn't re-read files it hasn't changed

### Claude Code mode
Each attempt is a fresh CLI invocation, but with accumulated context:
- Attempt 1: sees test output → writes files
- Attempt 2: new invocation with original context + retry message containing updated test output
- The agent re-reads the workspace (files from attempt 1 are already there)
- Less efficient but simpler; works well because Claude Code can `Read` the workspace naturally

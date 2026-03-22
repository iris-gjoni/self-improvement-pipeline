# Architecture

## Overview

The pipeline is a sequential, agentic software development loop. A feature request enters at one end; working, tested, verified code exits the other — with an optional self-improvement pass at the end.

```
Feature Request
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  runner.py — PipelineRunner                             │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 1. Req'mts   │→ │  2. Plan     │→ │ 3. TDD Red   │  │
│  └──────────────┘  └──────────────┘  └──────┬───────┘  │
│                                             │ (failing tests)
│  ┌──────────────────────────────────────────┘          │
│  │                                                     │
│  ▼                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 4. TDD Green │→ │ 5. Verify    │→ │ 6. Integrate │  │
│  │  (with retry)│  │              │  │              │  │
│  └──────────────┘  └──────────────┘  └──────┬───────┘  │
│                                             │          │
└─────────────────────────────────────────────┼──────────┘
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │  7. Post-mortem  │
                                    │  (Opus analysis) │
                                    └────────┬─────────┘
                                             │
                                             ▼
                                    proposals/RUN_ID.json
                                             │
                                    python apply_proposal.py
                                             │
                                    ┌────────┴─────────┐
                                    │ Human Review      │
                                    │ approve / reject  │
                                    └────────┬─────────┘
                                             │
                                    git commit [self-improve]
                                    EVOLUTION.md updated
```

## Components

### `runner.py` — PipelineRunner

The orchestration layer. It:
- Loads `pipeline.json` to know which steps to run and in what order
- Creates a timestamped run directory under `runs/`
- Initialises the workspace with language-specific boilerplate
- Dispatches each step to the correct runner (API or Claude Code CLI)
- Handles the TDD Green retry loop (re-invokes the agent with test failure output)
- Saves all step outputs as JSON artifacts
- Supports resuming interrupted runs (`--resume`)

### `utils/agent.py` — AgentRunner

The API-mode agent executor. It implements the tool-use loop:
1. Sends a `messages.create` request with tool definitions
2. Executes tool calls (`write_file`, `read_file`, `list_files`, `run_tests`)
3. Feeds tool results back to the model
4. Repeats until the `complete` tool is called
5. Returns the `complete` payload

Tools available per step type:
- **Structured steps**: `complete` only
- **Code-writing steps**: `write_file`, `read_file`, `list_files`, `complete`
- **TDD Green / Integration**: above + `run_tests`
- **Post-mortem**: `complete` with the full proposal schema

### `utils/claude_code_runner.py` — ClaudeCodeRunner

The Claude Code CLI mode executor. Instead of a tool-use loop, it:
1. Combines the system prompt and user message into a single prompt string
2. Appends a mode-specific addendum that translates tool instructions to native Claude Code equivalents
3. Invokes `claude --print -p "..." --allowedTools "..." --output-format json`
4. Parses the JSON response and extracts the result

For code-writing steps, Claude Code uses its native Write/Edit/Bash/Read tools directly. No custom tool implementation is needed.

### `utils/executor.py` — WorkspaceExecutor

Handles all subprocess execution inside the workspace:
- `run_tests()` — runs `pytest` / `jest`, parses output into a structured result
- `run_integration_tests()` — runs the integration-specific command
- `run_type_check()` — runs `mypy` / `tsc --noEmit`
- `install_dependencies()` — runs `pip install` / `npm install`
- `write_workspace_file()` / `read_workspace_file()` — safe file I/O with path validation

### `utils/context.py` — ContextBuilder

Builds the user message that each agent receives. Different steps get different context:
- Early steps (Requirements) only see the feature request
- Later steps (TDD Green) see all prior step outputs + full workspace file contents
- Post-mortem sees everything including timing data and pipeline config

The builder reads step outputs from `self.context` (the accumulated run state) and assembles a Markdown document for the agent.

### `utils/logger.py` — StepLogger

Persists run state to disk:
- `run.json` — run metadata, step statuses, and the full accumulated context
- `{step_id}.json` — each step's raw output
- `events.jsonl` — timestamped event log for debugging

### `postmortem.py`

Standalone script to run a post-mortem on any completed run. Useful when:
- The post-mortem step was skipped during the original run (`--skip-postmortem`)
- You want to re-run the post-mortem on an older run after changing the post-mortem prompt

### `apply_proposal.py`

The human-in-the-loop interface for self-improvement. It:
1. Loads a proposal JSON file from `proposals/`
2. Displays each proposal with its rationale and file operations
3. Prompts the user to `[a]pply`, `[r]eject`, or `[v]iew` (full diff)
4. Writes approved changes to disk
5. Appends an entry to `EVOLUTION.md`
6. Creates a `[self-improve]` git commit

## Data Flow

### Between steps

Each step's output is stored in `self.context[step_id]` and written to `runs/{run_id}/{step_id}.json`. The `ContextBuilder` reads this accumulated context and renders it as Markdown for subsequent agents.

This means agents receive prior work as human-readable Markdown, not raw JSON references. This keeps prompts natural and avoids marshalling complexity.

### Workspace files

Generated code lives in `runs/{run_id}/workspace/`. This directory is:
- Initialised with language-specific boilerplate before the pipeline runs
- Written to by TDD Red (tests), TDD Green (implementation), Integration (integration tests)
- Read by Verification (to review the code)
- Excluded from git by `.gitignore` (generated code is not tracked)

### Proposals

Post-mortem output is saved to `proposals/{run_id}.json` with `status: "pending"`. After `apply_proposal.py` processes it, the status changes to `"applied"` or `"rejected"` and individual proposals are marked with `applied: true` or `rejected: true`.

## Design Decisions

**Why data-driven pipeline config?**
`pipeline.json` defines the steps, not Python code. This means the self-improvement process can add, remove, or reorder steps by modifying a JSON file — no code change needed.

**Why separate API and Claude Code modes?**
API mode gives precise control over tool schemas and structured output parsing. Claude Code mode gives agents their full native toolset (especially powerful for code-writing). The two modes are configurable per-step so you can use the best tool for each job.

**Why require human approval for proposals?**
Autonomous self-modification without review risks compounding errors. A bad proposal applied automatically could degrade the pipeline. Human approval keeps the loop safe while still making it easy to apply good changes quickly.

**Why git-commit every improvement?**
Git provides a complete, immutable audit trail. You can always `git revert` a bad self-improvement, and `git log --grep="\[self-improve\]"` gives a complete timeline of how the pipeline evolved.

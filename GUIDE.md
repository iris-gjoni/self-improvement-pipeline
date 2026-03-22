# Self-Improving Pipeline — Complete Guide

## What This Is

This is an **agentic software development pipeline** that uses AI (Claude) to build and maintain software projects. You describe what you want in plain English, and the pipeline does the rest: it writes requirements, designs an architecture, writes failing tests, implements the code until all tests pass, verifies the requirements were actually met, runs integration tests, and documents the project.

After every run, an AI post-mortem analyses what went well and what didn't, then proposes improvements to the pipeline itself. Over time, the pipeline learns from its own runs and gets better at building software — hence "self-improving".

### Why use this instead of just asking Claude directly?

Asking Claude directly in a chat is great for one-off tasks, but it has no structure, no verification, and no memory across sessions. This pipeline gives you:

- **Structured process** — requirements before code, tests before implementation, verification after
- **Test-Driven Development** — code is only accepted when all tests pass
- **Persistent project memory** — every run is logged; the pipeline knows your project's history
- **Self-improvement** — the pipeline proposes its own upgrades after each run
- **Reproducibility** — every decision, file written, and test result is saved in `runs/`
- **Multiple execution modes** — headless (API), headless CLI, or fully interactive where you guide each step yourself

---

## Prerequisites

### Install dependencies

```bash
pip install anthropic rich
```

### Set your API key (for API mode)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Install Claude Code CLI (for claude_code or interactive mode)

```bash
npm install -g @anthropic-ai/claude-code
```

Verify it works:

```bash
python runner.py --check-cli
```

---

## Core Concepts

### The pipeline steps

Every run goes through up to 8 steps in order:

| # | Step | What it does |
|---|------|-------------|
| 1 | **Requirements** | Turns your feature request into structured acceptance criteria (AC-001, AC-002, ...) |
| 2 | **Plan** | Designs the architecture: file structure, interfaces, dependencies, test strategy |
| 3 | **TDD Red** | Writes tests for every acceptance criterion — tests must FAIL at this point (no implementation yet) |
| 4 | **TDD Green** | Implements the code until ALL tests pass; retries up to 5 times if tests keep failing |
| 5 | **Verification** | Checks that every acceptance criterion is genuinely satisfied — not just tests passing |
| 6 | **Integration** | Writes and runs end-to-end integration tests covering real workflows |
| 7 | **Post-mortem** | Analyses the whole run and proposes improvements to the pipeline itself |
| 8 | **Doc Update** | Creates or updates `docs/projects/{name}/` with README, architecture, changelog |

Steps 6, 7, and 8 are optional — the pipeline keeps going even if they fail.

### TDD (Test-Driven Development)

The pipeline enforces a strict Red-Green cycle:
- **Red phase**: tests are written first, with no implementation. The pipeline verifies they actually fail.
- **Green phase**: the implementation is written. The pipeline runs tests after each attempt. If they still fail, it tries again (up to 5 times) with the failure output fed back to the agent.

This means you always end up with real test coverage, not tests written to match code that already existed.

### The self-improvement loop

After every run, the post-mortem step (powered by the most capable model) generates a JSON proposal file in `proposals/`. You review it with `apply_proposal.py`, approve or reject each suggestion, and the accepted ones are written to the pipeline files and committed to git with a `[self-improve]` tag. The full history is in `EVOLUTION.md`.

### Execution modes

| Mode | How it works | When to use |
|------|-------------|-------------|
| `api` | Calls the Anthropic API directly via SDK | Default; requires a funded API key |
| `claude_code` | Runs `claude --print` as a subprocess (headless) | Requires Claude Max plan |
| `interactive` | Launches `claude` as a live terminal session for each step | When you want to guide or oversee each step yourself |

You set the mode with `--mode <mode>` on any command. The default is set in `pipeline.json`.

---

## Quickstart

### Create a brand new project

```bash
python runner.py "Build a REST API for managing todo items" --project-name todo-api --language python
```

The pipeline will:
1. Create a workspace at `runs/{timestamp}/workspace/`
2. Register `todo-api` in the project registry
3. Run all 8 steps
4. Print a summary table at the end

### Create a project in a specific directory

```bash
python runner.py "Build a snake game using tkinter" \
  --project-name snake-game \
  --project-dir "C:\Users\Iris\.irisai\snake-game" \
  --language python
```

When `--project-dir` is specified, the pipeline works directly in that folder instead of creating a `runs/` workspace.

### TypeScript project

```bash
python runner.py "Build a CLI tool for file encryption" \
  --project-name file-encryptor \
  --language typescript
```

---

## Working with Existing Projects

Once a project has been registered (either by a previous pipeline run or by pointing `--project-dir` at it), the pipeline knows about it and can maintain it.

### Add a feature

```bash
python runner.py "Add user authentication with JWT tokens" --project-name todo-api
```

The pipeline will look up `todo-api` in the registry, load its existing code and docs for context, and run the full cycle to add the feature alongside all existing code.

### Fix a bug

```bash
python runner.py "Fix the race condition in the login handler" --project-name todo-api
```

Same flow — requirements are generated specifically for the bug fix, tests are written to reproduce it, then implementation fixes it.

### Point at a project by directory

```bash
python runner.py "Add pagination to the results list" --project-dir /path/to/my-project
```

The pipeline auto-detects the language from the project files and registers it on first run.

### List all known projects

```bash
python runner.py --list-projects
```

---

## Execution Modes in Detail

### API mode (default)

Uses the Anthropic SDK directly. Requires `ANTHROPIC_API_KEY` with credits in your Anthropic Console account.

```bash
python runner.py "Build a REST API" --project-name my-api
# or explicitly:
python runner.py "Build a REST API" --project-name my-api --mode api
```

### Claude Code CLI mode (headless)

Runs `claude --print` as a subprocess. Each step is a single CLI invocation; Claude Code uses its own file tools (Write, Edit, Bash) natively. Requires a Claude Max plan.

```bash
python runner.py "Build a REST API" --project-name my-api --mode claude_code
```

### Interactive mode

Launches a live `claude` terminal session for each step. You can watch, guide, or modify what Claude does in real time. When you're satisfied, type `/exit` to end the session and the pipeline captures the results and moves to the next step.

```bash
python runner.py "Build a REST API" --project-name my-api --mode interactive
```

**How interactive steps work:**

- The pipeline writes the full task context (system prompt + prior step outputs) to a `_task_{step}.md` file in the run directory
- It launches `claude` pointing at that file — Claude reads it and begins working
- For **structured steps** (requirements, plan, verification, postmortem): Claude writes its JSON output to `_step_output.json` and you type `/exit`
- For **code-writing steps** (tdd_red, tdd_green, integration, doc_update): Claude writes files directly into the workspace; type `/exit` when done
- For **TDD Green**: after your session ends, the pipeline runs the tests. If they still fail and retries remain, it asks you `[r]etry / [s]kip` before opening another session

Interactive mode requires a real terminal (can't be run headlessly).

---

## Running Steps Manually

### Re-run a single step

If a step failed, or you want to redo it with a different approach:

```bash
# Re-run tdd_green on the most recent run
python runner.py --step tdd_green

# Re-run on a specific run
python runner.py --step tdd_green --run-id 2026-03-22T143000

# Re-run interactively
python runner.py --step tdd_green --mode interactive
```

Valid step IDs: `requirements`, `plan`, `tdd_red`, `tdd_green`, `verification`, `integration`, `postmortem`, `doc_update`

Re-running a step overwrites its previous result in the run's `run.json` and creates a fresh `{step_id}.json` artifact. All prior step context (e.g. plan, test output) is still available to the agent.

### Resume an interrupted run

If the pipeline was interrupted (Ctrl+C, crash, network error):

```bash
python runner.py --resume 2026-03-22T143000
```

This reloads the run state and skips all steps that already completed successfully, continuing from where it left off.

### List all runs

```bash
python runner.py --list-runs
```

---

## The Self-Improvement Loop

### How it works

After each run, the post-mortem step generates a `proposals/{run_id}.json` file containing concrete suggestions to improve the pipeline. Examples of what it might propose:

- Rewrite an agent prompt to be clearer
- Add a new pipeline step
- Change `tdd_green_max_attempts` from 5 to 7
- Update the README
- Create a reusable skill file

### Reviewing proposals

```bash
# Review the most recent pending proposal
python apply_proposal.py

# Review a specific proposal
python apply_proposal.py proposals/2026-03-22T143000.json

# List all proposals
python apply_proposal.py --list

# Preview what would change without applying anything
python apply_proposal.py --dry-run

# Apply everything without prompting (use with care)
python apply_proposal.py --auto-apply
```

When reviewing interactively, for each proposal you're shown:
- The rationale (why the change is needed)
- The exact file content that would be written
- Options: `[a]pply`, `[r]eject`, `[v]iew full diff`

### What happens when you apply a proposal

1. The file is written (agent prompt, pipeline.json, etc.)
2. A summary is appended to `EVOLUTION.md`
3. A git commit is made with the tag `[self-improve]`

### Viewing improvement history

```bash
# All self-improvement commits
git log --grep="\[self-improve\]" --oneline

# What changed in a specific improvement
git show <commit-hash>

# Full narrative history
cat EVOLUTION.md
```

### Running the post-mortem separately

If you skipped the post-mortem during a run (or want to re-run it):

```bash
# Most recent run
python postmortem.py

# Specific run
python postmortem.py 2026-03-22T143000

# List available runs
python postmortem.py --list
```

---

## Configuration

### pipeline.json

The main configuration file. Key settings:

```json
{
  "models": {
    "agent": "claude-sonnet-4-6",
    "postmortem": "claude-opus-4-6"
  },
  "execution": {
    "tdd_green_max_attempts": 5,
    "agent_max_tokens": 8192,
    "postmortem_max_tokens": 16000
  },
  "execution_mode": "api",
  "docs_repo": "docs"
}
```

**Changing the model**: set `"agent"` to any Claude model ID, e.g. `"claude-haiku-4-5-20251001"` for a cheaper/faster model.

**Per-step mode override**: add `"execution_mode": "interactive"` to any step definition in the `steps` array to run only that step differently from the global default.

**Docs location**: `docs_repo` can be a relative path (from the pipeline root) or an absolute path, allowing you to keep project docs in a separate repository.

### languages.json

Controls how code is compiled and tested for each language. Supports `python`, `typescript`, `javascript`. Each entry defines:

- Test command (e.g. `pytest -v`)
- Integration test command
- Type check command (mypy / tsc)
- Install command (pip / npm)
- Boilerplate files written to fresh workspaces

To add a new language, add an entry following the same structure.

### Agent prompts (`agents/`)

Each pipeline step has a corresponding agent prompt in `agents/`:

| File | Step |
|------|------|
| `01_requirements.md` | Requirements Generation |
| `02_plan.md` | Implementation Plan |
| `03_tdd_red.md` | TDD Red Phase |
| `04_tdd_green.md` | TDD Green + Implementation |
| `05_verification.md` | Requirements Verification |
| `06_integration.md` | Integration Tests |
| `07_postmortem.md` | Post-mortem Analysis |
| `08_doc_update.md` | Documentation Update |

These are editable markdown files. The post-mortem can propose rewrites to them, or you can edit them directly. They support `{language}` and `{test_framework}` template variables.

---

## Directory Structure

```
self-improvement-pipeline/
├── runner.py              # Main entry point — run this for everything
├── apply_proposal.py      # Review and apply self-improvement proposals
├── postmortem.py          # Run post-mortem on any completed run
├── pipeline.json          # Step definitions, models, execution settings
├── languages.json         # Language-specific test/build/install commands
├── projects.json          # Project registry (auto-managed)
├── EVOLUTION.md           # History of all self-improvements applied
├── GUIDE.md               # This file
│
├── agents/                # System prompts for each pipeline step
│   ├── 01_requirements.md
│   ├── 02_plan.md
│   ├── 03_tdd_red.md
│   ├── 04_tdd_green.md
│   ├── 05_verification.md
│   ├── 06_integration.md
│   ├── 07_postmortem.md
│   └── 08_doc_update.md
│
├── utils/                 # Internal modules (not for direct use)
│   ├── agent.py           # API-mode tool-use loop
│   ├── claude_code_runner.py  # Headless CLI runner
│   ├── interactive_runner.py  # Interactive terminal session runner
│   ├── executor.py        # Runs tests/builds in workspace
│   ├── context.py         # Builds context messages between steps
│   ├── logger.py          # Saves run artifacts to disk
│   └── project_registry.py    # Manages projects.json
│
├── runs/                  # One directory per pipeline run
│   └── 2026-03-22T143000/
│       ├── run.json           # Metadata, status, all step results
│       ├── workspace/         # Generated code (new projects only)
│       ├── requirements.json  # Step 1 output
│       ├── plan.json          # Step 2 output
│       ├── tdd_red.json       # Step 3 output
│       ├── tdd_green.json     # Step 4 output
│       ├── verification.json  # Step 5 output
│       ├── integration.json   # Step 6 output
│       ├── postmortem.json    # Step 7 output
│       └── events.jsonl       # Event log (start/complete per step)
│
├── proposals/             # Post-mortem proposals awaiting review
│   └── 2026-03-22T143000.json
│
├── skills/                # Reusable skills created by self-improvement
│
└── docs/
    ├── self/              # Documentation about this pipeline itself
    └── projects/          # Per-project living documentation
        └── {project-name}/
            ├── README.md
            ├── architecture.md
            ├── requirements.md
            └── CHANGELOG.md
```

---

## Complete CLI Reference

### runner.py

```
python runner.py "Feature request"
    [--project-name NAME]     Project identifier (auto-generated if omitted)
    [--project-dir PATH]      Path to existing project directory
    [--language LANG]         python | typescript | javascript (auto-detected if omitted)
    [--mode MODE]             api | claude_code | interactive
    [--skip-postmortem]       Skip the post-mortem step
    [--resume RUN_ID]         Resume an interrupted run
    [--step STEP_ID]          Run a single step against an existing run
    [--run-id RUN_ID]         Target run for --step (defaults to most recent)
    [--list-runs]             List all previous runs
    [--list-projects]         List all known projects
    [--check-cli]             Verify Claude Code CLI is installed
```

### apply_proposal.py

```
python apply_proposal.py [PROPOSAL_FILE]
    [--list]        List all proposals and their status
    [--auto-apply]  Apply all pending proposals without prompting
    [--dry-run]     Preview changes without writing anything
```

### postmortem.py

```
python postmortem.py [RUN_ID]
    [--list]        List available runs
```

---

## Common Workflows

### Build a new project from scratch

```bash
python runner.py "Build a task manager CLI with add/list/complete/delete commands" \
  --project-name task-cli \
  --language python
```

### Maintain a project over time

```bash
# First time — registers the project
python runner.py "Add export to CSV feature" --project-dir /path/to/task-cli

# Subsequent runs — looked up by name
python runner.py "Fix bug where completed tasks still appear in list" --project-name task-cli
python runner.py "Add due dates to tasks" --project-name task-cli
```

### Guided interactive run (you oversee each step)

```bash
python runner.py "Refactor the database layer to use SQLAlchemy" \
  --project-name task-cli \
  --mode interactive
```

### Re-run a failed step

```bash
# See which run failed
python runner.py --list-runs

# Re-run just the failing step
python runner.py --step tdd_green --run-id 2026-03-22T143000

# Or interactively so you can help
python runner.py --step tdd_green --run-id 2026-03-22T143000 --mode interactive
```

### Review and apply self-improvements

```bash
# After a run completes, review the proposals it generated
python apply_proposal.py

# See the history of all improvements applied so far
cat EVOLUTION.md
```

### Use a cheaper/faster model for a run

Edit `pipeline.json` temporarily:

```json
"models": {
  "agent": "claude-haiku-4-5-20251001",
  "postmortem": "claude-haiku-4-5-20251001"
}
```

Then run normally. Change it back to Sonnet/Opus for production quality.

---

## How Projects Are Tracked

The project registry (`projects.json`) records:
- Project name and language
- The project directory (if any)
- Every run ID that touched the project
- When the last run was
- Where the project's docs live

On every run the pipeline automatically:
1. Looks up the project by name, then by directory
2. Registers it if it's new
3. Feeds prior run history and existing docs into the agent context
4. Updates the registry with the new run ID

This means agents working on an existing project always know what has already been built, what tests exist, and what the architecture looks like — they don't start from scratch.

---

## Safety Notes

- Post-mortem proposals require **human review by default** — `apply_proposal.py` shows you exactly what will change before writing anything
- Proposals can only write to: `agents/`, `pipeline.json`, `languages.json`, `skills/`, `README.md`, `docs/` — path traversal and absolute paths are rejected
- All applied improvements are git-committed for full auditability
- Use `--dry-run` to preview proposal changes without applying them
- In interactive mode, you are present in every step — nothing happens without you seeing it

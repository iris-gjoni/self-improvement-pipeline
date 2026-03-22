# Self-Improving Software Development Pipeline

An agentic pipeline that uses AI (Claude) to **build new projects from scratch** and **maintain existing ones** — through structured requirements, TDD, verification, and integration tests. After every run, a post-mortem analyses what happened and proposes improvements to the pipeline itself.

## Why use this instead of just asking Claude?

Asking Claude in a chat is great for one-off tasks, but has no structure, no verification, and no memory across sessions. This pipeline gives you:

- **Structured process** — requirements before code, tests before implementation, verification after
- **Test-Driven Development** — code is only accepted when all tests pass
- **Persistent project memory** — every run is logged; the pipeline knows your project's history
- **Self-improvement** — the pipeline proposes its own upgrades after each run
- **Reproducibility** — every decision, file written, and test result is saved in `runs/`
- **Multiple execution modes** — headless API, headless CLI, or fully interactive where you guide each step yourself

---

## How It Works

Every run goes through up to 8 steps:

| # | Step | What it does |
|---|------|-------------|
| 1 | **Requirements** | Turns your feature request into structured acceptance criteria (AC-001, AC-002, ...) |
| 2 | **Plan** | Designs the architecture: file structure, interfaces, dependencies, test strategy |
| 3 | **TDD Red** | Writes tests for every acceptance criterion — tests must **FAIL** (no implementation yet) |
| 4 | **TDD Green** | Implements the code until ALL tests pass; retries up to 5 times if tests keep failing |
| 5 | **Verification** | Checks every acceptance criterion is genuinely satisfied — not just tests passing |
| 6 | **Integration** | Writes and runs end-to-end integration tests covering real workflows *(optional)* |
| 7 | **Post-mortem** | Analyses the whole run and proposes improvements to the pipeline itself *(optional)* |
| 8 | **Doc Update** | Creates/updates `docs/projects/{name}/` with README, architecture, changelog *(optional)* |

### TDD Red/Green cycle

The pipeline enforces a strict cycle: tests are written first with no implementation (they must fail), then the implementation is written. After each attempt the pipeline runs the tests, and if they still fail it tries again (up to 5 times) with the failure output fed back to the agent. You always end up with real test coverage.

### Self-improvement loop

After every run, the post-mortem generates a `proposals/{run_id}.json` with concrete suggestions — rewrite a prompt, add a step, tune a setting. You review them with `apply_proposal.py`, approve or reject each one, and accepted changes are written to the pipeline files and committed to git with a `[self-improve]` tag. Full history in `EVOLUTION.md`.

---

## Prerequisites

```bash
pip install anthropic rich
export ANTHROPIC_API_KEY=sk-ant-...         # for API mode
npm install -g @anthropic-ai/claude-code    # for claude_code or interactive mode
```

---

## Quick Start

### New project

```bash
python runner.py "Build a REST API for todo items" --project-name todo-api --language python
```

The pipeline creates a workspace at `runs/{timestamp}/workspace/`, registers the project, runs all 8 steps, and prints a summary.

### New project in a specific directory

```bash
python runner.py "Build a snake game using tkinter" \
  --project-name snake-game \
  --project-dir "C:\path\to\snake-game" \
  --language python
```

### TypeScript project

```bash
python runner.py "Build a CLI tool for file encryption" \
  --project-name file-encryptor \
  --language typescript
```

### Existing project — add a feature

```bash
python runner.py "Add user authentication with JWT tokens" --project-name todo-api
```

The pipeline loads the existing code, docs, and run history as context, then runs the full cycle to add the feature alongside what's already there.

### Existing project — fix a bug

```bash
python runner.py "Fix the race condition in the login handler" --project-name todo-api
```

Requirements are generated specifically for the bug, tests reproduce it, then the fix is implemented.

### Point at a project by directory

```bash
python runner.py "Add pagination to the results" --project-dir /path/to/my-project
```

Language is auto-detected; the project is registered on first run.

---

## Execution Modes

| Mode | How it works | Requires |
|------|-------------|----------|
| `api` | Calls the Anthropic API via SDK | Funded `ANTHROPIC_API_KEY` |
| `claude_code` | Runs `claude --print` headlessly as a subprocess | Claude Max plan |
| `interactive` | Launches a live `claude` terminal session for each step | Claude Code CLI + real terminal |

Set with `--mode <mode>`. Default is configured in `pipeline.json`.

### Interactive mode in detail

```bash
python runner.py "Refactor the auth layer" --project-name my-app --mode interactive
```

For each step, the pipeline writes the full task context to a markdown file in the run directory, then launches a live `claude` session:

- **Structured steps** (requirements, plan, verification, postmortem) — Claude analyses the context, writes its JSON output to `_step_output.json`, then you type `/exit`
- **Code-writing steps** (tdd_red, tdd_green, integration, doc_update) — Claude writes files directly into the workspace; type `/exit` when done
- **TDD Green** — after your session ends, the pipeline runs the tests. If they still fail and retries remain, it asks `[r]etry / [s]kip` before opening another session

You can watch, guide, correct, or collaborate on every step in real time.

---

## Running Steps Manually

### Re-run a single step

```bash
# Most recent run
python runner.py --step tdd_green

# Specific run
python runner.py --step tdd_green --run-id 2026-03-22T143000

# Interactively
python runner.py --step tdd_green --run-id 2026-03-22T143000 --mode interactive
```

Valid step IDs: `requirements`, `plan`, `tdd_red`, `tdd_green`, `verification`, `integration`, `postmortem`, `doc_update`

Re-running overwrites the previous result in `run.json` but all prior step context (plan, tests, etc.) remains available to the agent.

### Resume an interrupted run

```bash
python runner.py --resume 2026-03-22T143000
```

Skips completed steps, continues from where it left off.

---

## Self-Improvement

### Reviewing proposals

```bash
python apply_proposal.py                          # Most recent pending proposal
python apply_proposal.py proposals/2026-...json   # Specific proposal
python apply_proposal.py --list                   # List all proposals
python apply_proposal.py --dry-run                # Preview without applying
python apply_proposal.py --auto-apply             # Apply all without prompting
```

For each proposal you see: the rationale, the exact file content to be written, and `[a]pply / [r]eject / [v]iew diff` options.

### What applying does

1. Writes the file (agent prompt, `pipeline.json`, etc.)
2. Appends a summary to `EVOLUTION.md`
3. Creates a `[self-improve]` git commit

### Viewing the history

```bash
git log --grep="\[self-improve\]" --oneline   # All self-improvement commits
git show <commit-hash>                         # What changed in a specific one
cat EVOLUTION.md                               # Full narrative history
```

### Re-run post-mortem on any completed run

```bash
python postmortem.py                    # Most recent run
python postmortem.py 2026-03-22T143000  # Specific run
python postmortem.py --list             # List available runs
```

---

## How Projects Are Tracked

The project registry (`projects.json`) records each project's name, language, directory, every run ID, last run time, and docs location. On every run the pipeline automatically looks up the project (by name, then by directory), registers it if new, feeds prior history and existing docs into the agent context, and updates the registry. Agents on existing projects always know what's already been built.

```bash
python runner.py --list-projects   # All known projects
python runner.py --list-runs       # All previous runs
```

---

## Configuration

### pipeline.json

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

- **`"agent"`** — any Claude model ID (e.g. `"claude-haiku-4-5-20251001"` for cheaper/faster runs)
- **`"execution_mode"`** — global default mode; override per-step by adding `"execution_mode"` to any step in the `steps` array
- **`"docs_repo"`** — relative or absolute path to the documentation root; can point to a separate repository

### languages.json

Defines test commands, type-check commands, install commands, and workspace boilerplate for each language. Supports `python`, `typescript`, `javascript`. Add an entry following the same structure to support a new language.

### Agent prompts (`agents/`)

Each step has an editable system prompt. The post-mortem can propose rewrites, or you can edit them directly. Template variables `{language}` and `{test_framework}` are substituted at runtime.

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

---

## Complete CLI Reference

### runner.py

```
python runner.py "Feature request"
    [--project-name NAME]     Project identifier (auto-generated if omitted)
    [--project-dir PATH]      Path to existing project directory
    [--language LANG]         python | typescript | javascript
    [--mode MODE]             api | claude_code | interactive
    [--skip-postmortem]       Skip the post-mortem step
    [--resume RUN_ID]         Resume an interrupted run
    [--step STEP_ID]          Re-run one step against an existing run
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

## Directory Structure

```
self-improvement-pipeline/
├── runner.py                  # Main entry point
├── apply_proposal.py          # Review and apply self-improvement proposals
├── postmortem.py              # Standalone post-mortem runner
├── pipeline.json              # Step definitions, models, execution settings
├── languages.json             # Language-specific test/build/install configs
├── projects.json              # Project registry (auto-managed)
├── GUIDE.md                   # Full user guide
├── EVOLUTION.md               # Self-improvement history
│
├── agents/                    # System prompts — one per pipeline step
│
├── utils/
│   ├── agent.py               # API-mode tool-use loop (AgentRunner)
│   ├── claude_code_runner.py  # Headless CLI runner (ClaudeCodeRunner)
│   ├── interactive_runner.py  # Interactive session runner (InteractiveRunner)
│   ├── executor.py            # Runs tests/builds in workspace
│   ├── context.py             # Builds context messages between steps
│   ├── logger.py              # Saves run artifacts to disk
│   └── project_registry.py   # Manages projects.json
│
├── runs/                      # One directory per pipeline run (gitignored)
│   └── 2026-03-22T143000/
│       ├── run.json           # Full run metadata and all step results
│       ├── workspace/         # Generated code (new projects only)
│       └── {step_id}.json     # Per-step output artifacts
│
├── proposals/                 # Post-mortem proposals awaiting review
├── skills/                    # Reusable skills created by self-improvement
└── docs/
    ├── self/                  # Documentation about this pipeline
    └── projects/              # Per-project living docs (auto-generated)
        └── {project-name}/
            ├── README.md
            ├── architecture.md
            ├── requirements.md
            └── CHANGELOG.md
```

---

## Safety Notes

- Post-mortem proposals require **human approval** before being applied (default)
- Proposals can only write to: `agents/`, `pipeline.json`, `languages.json`, `skills/`, `README.md`, `docs/` — path traversal and absolute paths are rejected
- All self-improvements are git-committed for full auditability
- Use `--dry-run` to preview proposal changes without applying them
- In interactive mode, you are present in every step — nothing happens without you seeing it

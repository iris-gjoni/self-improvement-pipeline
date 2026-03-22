# Self-Improving Software Development Pipeline

An agentic pipeline for **creating new projects from scratch** and **maintaining existing projects** — using TDD, requirements verification, and integration tests. After each run, an Opus-powered post-mortem analyses the work and proposes improvements to the pipeline itself.

## How It Works

```
Feature Request
      │
      ▼
┌─────────────────┐
│  1. Requirements │  Sonnet generates structured spec with acceptance criteria
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Plan         │  Sonnet designs architecture, file structure, interfaces
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. TDD Red      │  Sonnet writes failing tests for all acceptance criteria
└────────┬────────┘
         │  (tests written, verified to FAIL)
         ▼
┌─────────────────┐
│  4. TDD Green    │  Sonnet implements code until ALL tests pass (up to 5 retries)
└────────┬────────┘
         │  (tests verified to PASS + type check)
         ▼
┌─────────────────┐
│  5. Verification │  Sonnet checks every AC is genuinely satisfied
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Integration  │  Sonnet writes & runs end-to-end integration tests
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  7. Post-mortem  │  Opus analyses the full run and proposes pipeline improvements
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  8. Doc Update   │  Sonnet creates/updates living docs in docs/projects/{name}/
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  apply_proposal.py                       │
│  Human reviews proposals, approves/rejects│
│  Changes committed with [self-improve]    │
└─────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

```bash
pip install anthropic rich
export ANTHROPIC_API_KEY=sk-ant-...
```

### New project (build from scratch)

```bash
# Create a new project — auto-names it from the feature request
python runner.py "Build a REST API for todo items" --language python

# Give it an explicit name (used for docs/projects/ folder and registry)
python runner.py "Build a REST API for todo items" --project-name todo-api

# TypeScript project
python runner.py "Build a CLI tool for file encryption" --language typescript --project-name file-encryptor
```

### Existing project (add features or fix bugs)

```bash
# Point at an existing project — language auto-detected, project auto-registered on first run
python runner.py "Add password reset flow" --project-dir /path/to/myproject

# Explicit name and language override
python runner.py "Fix the login race condition" --project-dir /path/to/myproject --project-name my-app --language python

# Subsequent runs on the same project (looked up by name)
python runner.py "Add email notifications" --project-name my-app
```

### Project registry

```bash
# List all known projects
python runner.py --list-projects

# List all previous runs
python runner.py --list-runs
```

### Other options

```bash
# Use Claude Code CLI for all steps
python runner.py "..." --mode claude_code

# Check Claude Code CLI is available
python runner.py --check-cli

# Skip post-mortem (faster, no proposals generated)
python runner.py "..." --skip-postmortem

# Resume an interrupted run
python runner.py --resume 2026-03-22T143000
```

### Review self-improvement proposals

```bash
# Review most recent pending proposal (interactive)
python apply_proposal.py

# Review a specific proposal
python apply_proposal.py proposals/2026-03-22T143000.json

# List all proposals
python apply_proposal.py --list

# Apply all without prompting (use with care)
python apply_proposal.py --auto-apply

# Preview changes without applying
python apply_proposal.py --dry-run
```

### Run post-mortem on any completed run

```bash
# Most recent run
python postmortem.py

# Specific run
python postmortem.py 2026-03-22T143000

# List available runs
python postmortem.py --list
```

## Directory Structure

```
self-improvement-pipeline/
├── runner.py                  # Main pipeline entry point
├── postmortem.py              # Standalone post-mortem runner
├── apply_proposal.py          # Interactive proposal review/apply
├── pipeline.json              # Pipeline step definitions
├── languages.json             # Language-specific execution configs
├── requirements.txt           # Python dependencies
│
├── agents/                    # Agent system prompts (one per step)
│   ├── 01_requirements.md
│   ├── 02_plan.md
│   ├── 03_tdd_red.md
│   ├── 04_tdd_green.md
│   ├── 05_verification.md
│   ├── 06_integration.md
│   └── 07_postmortem.md
│
├── utils/                     # Internal modules
│   ├── agent.py               # Agent tool-use loop
│   ├── executor.py            # Workspace code execution
│   ├── context.py             # Context building between steps
│   └── logger.py              # Run artifact logging
│
├── runs/                      # One directory per pipeline run
│   └── 2026-03-22T143000/
│       ├── run.json           # Metadata, status, step results
│       ├── workspace/         # Generated code lives here
│       │   ├── src/
│       │   └── tests/
│       ├── requirements.json  # Step 1 output
│       ├── plan.json          # Step 2 output
│       ├── tdd_red.json       # Step 3 output
│       ├── tdd_green.json     # Step 4 output
│       ├── verification.json  # Step 5 output
│       ├── integration.json   # Step 6 output
│       ├── postmortem.json    # Step 7 output
│       └── events.jsonl       # Event log
│
├── proposals/                 # Post-mortem proposals (pending review)
│   └── 2026-03-22T143000.json
│
├── skills/                    # Skills created by self-improvement
│
├── EVOLUTION.md               # Human-readable self-improvement history
└── README.md                  # This file
```

## The Self-Improvement Loop

After each pipeline run, the post-mortem step (powered by Opus) analyses:

- **Agent output quality** — Were requirements complete? Were tests thorough? Did verification catch real issues?
- **Process failures** — Did any step fail or retry excessively?
- **Prompt quality** — Were agent prompts clear enough?
- **Missing steps** — Is there a step that should exist?
- **Structural improvements** — Better ordering, settings changes

Proposals are saved to `proposals/`. Run `apply_proposal.py` to review and apply them.

Each applied improvement is:
1. Written to the appropriate file (agent prompt, `pipeline.json`, etc.)
2. Appended to `EVOLUTION.md` with rationale
3. Committed to git with a `[self-improve]` tag

### Viewing the history

```bash
# See all self-improvement commits
git log --grep="\[self-improve\]" --oneline

# See exactly what changed in a specific improvement
git show <commit-hash>

# See the full narrative history
cat EVOLUTION.md
```

## Configuration

### pipeline.json

Controls step definitions, model selection, and execution settings:

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
  }
}
```

### languages.json

Controls how code is compiled and tested for each language. Supports `python`, `typescript`, `javascript`.

### Adding a pipeline step

1. Create an agent prompt in `agents/NN_stepname.md`
2. Add the step to `pipeline.json`
3. Restart the pipeline

The self-improvement process can also do this automatically via proposals.

## Documentation

Detailed documentation is in `docs/`:

| File | Contents |
|------|----------|
**Pipeline documentation** (`docs/self/`):

| File | Contents |
|------|----------|
| [`docs/self/architecture.md`](docs/self/architecture.md) | System design, components, data flow, design decisions |
| [`docs/self/pipeline-steps.md`](docs/self/pipeline-steps.md) | What each step does, inputs/outputs, quality signals, failure modes |
| [`docs/self/agent-prompts.md`](docs/self/agent-prompts.md) | How prompts work, tool sets, template variables, writing guidelines |
| [`docs/self/execution-modes.md`](docs/self/execution-modes.md) | API mode vs Claude Code CLI mode — trade-offs, config, per-step overrides |
| [`docs/self/self-improvement.md`](docs/self/self-improvement.md) | The improvement loop in detail — proposals, apply_proposal.py, git history |
| [`docs/self/adding-a-step.md`](docs/self/adding-a-step.md) | Step-by-step guide to adding a new pipeline step |
| [`docs/self/workspace-execution.md`](docs/self/workspace-execution.md) | Code execution, language support, adding a new language |

**Project documentation** (`docs/projects/`):

Auto-generated and maintained by the pipeline. One subdirectory per project, created on first run and updated on every subsequent run.

## Models Used

| Step | Model | Why |
|------|-------|-----|
| Requirements, Plan, TDD Red/Green, Verification, Integration | `claude-sonnet-4-6` | Fast, capable for structured code tasks |
| Post-mortem | `claude-opus-4-6` | Deep analysis of the full run, generating concrete improvement proposals |

## Safety Notes

- Post-mortem proposals require **human approval** before being applied (default behaviour)
- Proposals can only write to: `agents/`, `pipeline.json`, `languages.json`, `skills/`, `README.md`, `docs/`
- Path traversal and absolute paths are rejected
- All self-improvements are git-committed for full auditability
- Use `--dry-run` to preview changes without applying them

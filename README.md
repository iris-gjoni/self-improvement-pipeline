# Self-Improving Software Development Pipeline

An agentic pipeline for **creating new projects from scratch** and **maintaining existing projects** — using TDD, requirements verification, and integration tests. After each run, a post-mortem analyses the work and proposes improvements to the pipeline itself.

> For a complete user guide, see [GUIDE.md](GUIDE.md).

## How It Works

```
Feature Request
      |
      v
+------------------+
|  1. Requirements  |  Generates structured spec with acceptance criteria
+--------+---------+
         |
         v
+------------------+
|  2. Plan          |  Designs architecture, file structure, interfaces
+--------+---------+
         |
         v
+------------------+
|  3. TDD Red       |  Writes failing tests for all acceptance criteria
+--------+---------+
         |  (tests written, verified to FAIL)
         v
+------------------+
|  4. TDD Green     |  Implements code until ALL tests pass (up to 5 retries)
+--------+---------+
         |  (tests verified to PASS + type check)
         v
+------------------+
|  5. Verification  |  Checks every AC is genuinely satisfied
+--------+---------+
         |
         v
+------------------+
|  6. Integration   |  Writes and runs end-to-end integration tests
+--------+---------+
         |
         v
+------------------+
|  7. Post-mortem   |  Analyses the full run, proposes pipeline improvements
+--------+---------+
         |
         v
+------------------+
|  8. Doc Update    |  Creates/updates living docs in docs/projects/{name}/
+--------+---------+
         |
         v
+------------------------------------------+
|  apply_proposal.py                        |
|  Human reviews proposals, approves/rejects|
|  Changes committed with [self-improve]    |
+------------------------------------------+
```

## Quick Start

### Prerequisites

```bash
pip install anthropic rich
export ANTHROPIC_API_KEY=sk-ant-...
```

### New project (build from scratch)

```bash
# Auto-names from the feature request
python runner.py "Build a REST API for todo items" --language python

# Explicit name
python runner.py "Build a REST API for todo items" --project-name todo-api

# TypeScript
python runner.py "Build a CLI tool for file encryption" --language typescript --project-name file-encryptor
```

### Existing project (add features or fix bugs)

```bash
# Point at an existing project directory
python runner.py "Add password reset flow" --project-dir /path/to/myproject

# Subsequent runs by name (looked up from registry)
python runner.py "Add email notifications" --project-name my-app
```

### Execution modes

```bash
# Default: Anthropic SDK (requires funded API key)
python runner.py "..." --mode api

# Headless Claude Code CLI (requires Claude Max plan)
python runner.py "..." --mode claude_code

# Interactive: launches a live claude terminal session for each step
# You can watch, guide, and collaborate on each step in real time
python runner.py "..." --mode interactive
```

### Manual step execution

```bash
# Re-run a single step on the most recent run
python runner.py --step tdd_green

# Re-run a step on a specific run
python runner.py --step tdd_green --run-id 2026-03-22T143000

# Re-run a step interactively
python runner.py --step tdd_green --mode interactive

# Resume an interrupted run from where it left off
python runner.py --resume 2026-03-22T143000
```

### Project registry

```bash
python runner.py --list-projects   # List all known projects
python runner.py --list-runs       # List all previous runs
python runner.py --check-cli       # Verify Claude Code CLI is available
```

### Review self-improvement proposals

```bash
python apply_proposal.py                        # Most recent pending proposal
python apply_proposal.py proposals/2026-...json # Specific proposal
python apply_proposal.py --list                 # List all proposals
python apply_proposal.py --dry-run              # Preview without applying
python apply_proposal.py --auto-apply           # Apply all without prompting
```

### Run post-mortem on any completed run

```bash
python postmortem.py                  # Most recent run
python postmortem.py 2026-03-22T143000 # Specific run
python postmortem.py --list           # List available runs
```

## Directory Structure

```
self-improvement-pipeline/
├── runner.py                  # Main pipeline entry point
├── postmortem.py              # Standalone post-mortem runner
├── apply_proposal.py          # Interactive proposal review/apply
├── pipeline.json              # Pipeline step definitions and config
├── languages.json             # Language-specific execution configs
├── projects.json              # Project registry (auto-managed)
├── GUIDE.md                   # Complete user guide
├── EVOLUTION.md               # Human-readable self-improvement history
│
├── agents/                    # Agent system prompts (one per step)
│   ├── 01_requirements.md
│   ├── 02_plan.md
│   ├── 03_tdd_red.md
│   ├── 04_tdd_green.md
│   ├── 05_verification.md
│   ├── 06_integration.md
│   ├── 07_postmortem.md
│   └── 08_doc_update.md
│
├── utils/                     # Internal modules
│   ├── agent.py               # API-mode tool-use loop
│   ├── claude_code_runner.py  # Headless CLI runner
│   ├── interactive_runner.py  # Interactive terminal session runner
│   ├── executor.py            # Workspace code execution
│   ├── context.py             # Context building between steps
│   ├── logger.py              # Run artifact logging
│   └── project_registry.py   # Project registry management
│
├── runs/                      # One directory per pipeline run (gitignored)
│   └── 2026-03-22T143000/
│       ├── run.json           # Metadata, status, step results
│       ├── workspace/         # Generated code lives here
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
├── skills/                    # Skills created by self-improvement
└── docs/
    ├── self/                  # Pipeline documentation
    └── projects/              # Per-project living docs (auto-generated)
```

## The Self-Improvement Loop

After each pipeline run, the post-mortem step analyses:

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

```bash
git log --grep="\[self-improve\]" --oneline   # All self-improvement commits
cat EVOLUTION.md                               # Full narrative history
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
  },
  "execution_mode": "api"
}
```

Set `"agent"` to any Claude model ID. Set `"execution_mode"` to `"api"`, `"claude_code"`, or `"interactive"` as the global default. Override per-step with `"execution_mode"` on any step in the `steps` array.

### languages.json

Controls how code is compiled and tested. Supports `python`, `typescript`, `javascript`.

### Adding a pipeline step

1. Create an agent prompt in `agents/NN_stepname.md`
2. Add the step to `pipeline.json`
3. The self-improvement process can also do this automatically via proposals

## Documentation

| File | Contents |
|------|----------|
| [GUIDE.md](GUIDE.md) | Complete user guide — start here |
| [docs/self/architecture.md](docs/self/architecture.md) | System design, components, data flow |
| [docs/self/pipeline-steps.md](docs/self/pipeline-steps.md) | Each step in detail — inputs, outputs, failure modes |
| [docs/self/agent-prompts.md](docs/self/agent-prompts.md) | How prompts work, template variables, writing guidelines |
| [docs/self/execution-modes.md](docs/self/execution-modes.md) | API vs Claude Code CLI vs Interactive — trade-offs and config |
| [docs/self/self-improvement.md](docs/self/self-improvement.md) | The improvement loop in detail |
| [docs/self/adding-a-step.md](docs/self/adding-a-step.md) | Guide to adding a new pipeline step |
| [docs/self/workspace-execution.md](docs/self/workspace-execution.md) | Code execution, language support |

## Models Used

| Step | Default Model | Role |
|------|--------------|------|
| Requirements, Plan, TDD Red/Green, Verification, Integration, Doc Update | `claude-sonnet-4-6` | Structured code tasks |
| Post-mortem | `claude-opus-4-6` | Deep analysis, concrete improvement proposals |

Configurable in `pipeline.json`. Any Claude model ID is accepted.

## Safety Notes

- Post-mortem proposals require **human approval** before being applied (default behaviour)
- Proposals can only write to: `agents/`, `pipeline.json`, `languages.json`, `skills/`, `README.md`, `docs/`
- Path traversal and absolute paths are rejected
- All self-improvements are git-committed for full auditability
- Use `--dry-run` to preview changes without applying them

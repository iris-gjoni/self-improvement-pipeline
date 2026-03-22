# Self-Improvement

The pipeline improves itself over time through post-mortem analysis. This document explains the complete cycle: how analysis is generated, how proposals work, how they are applied, and how the history is preserved.

---

## The Cycle

```
1. Run the pipeline          → runs/{run_id}/
2. Post-mortem (Opus)        → proposals/{run_id}.json   [status: pending]
3. Human review              → apply_proposal.py
4. Apply approved changes    → agents/, pipeline.json, etc.
5. Git commit                → [self-improve] tag
6. EVOLUTION.md updated      → human-readable changelog
```

Repeat. Over time, the pipeline improves its agent prompts, step configuration, and process.

---

## Step 7: Post-mortem Analysis

The post-mortem step uses **Opus** to analyse the full run. It receives:
- All step outputs (requirements, plan, test results, verification, integration)
- Step timing data (how long each step took, how many retries)
- The current pipeline configuration (`pipeline.json` contents)
- All current agent prompts (`agents/*.md` contents)

Opus produces a structured output with:
1. **Analysis** — a narrative assessment of what happened and why
2. **Run summary** — overall quality (`excellent/good/fair/poor`) + key issues + key successes
3. **Proposals** — a list of concrete changes, each with complete file contents

### What triggers a good post-mortem

The post-mortem is most useful when:
- TDD Green required many retries (prompt or plan quality issue)
- Verification found gaps (requirements or tests were weak)
- A step failed entirely
- Integration tests revealed issues unit tests missed
- The generated code had poor quality (security issues, bad error handling)

It is also useful on successful runs — the model identifies what worked and suggests improvements to make good things consistent.

---

## Proposal Schema

Each proposal in `proposals/{run_id}.json` has this structure:

```json
{
  "id": "prop_1",
  "type": "update_agent | update_pipeline | add_step | remove_step | create_skill | update_docs | other",
  "title": "Improve requirements prompt to capture non-functional requirements",
  "rationale": "In this run, the requirements agent omitted NFRs entirely. The verifier flagged that password hashing strength was not specified. The requirements prompt should have an explicit NFR section.",
  "priority": "high | medium | low",
  "operations": [
    {
      "action": "write",
      "path": "agents/01_requirements.md",
      "content": "... complete new file content ..."
    }
  ]
}
```

Operations are file-level: `write` (create/overwrite), `append` (add to end), or `delete`.

### Allowed paths

Proposals can only write to these locations (enforced by `apply_proposal.py`):
- `agents/` — agent system prompts
- `pipeline.json` — pipeline step configuration
- `languages.json` — language execution config
- `skills/` — reusable skill files
- `README.md` — main documentation
- `docs/` — documentation folder

Absolute paths and `..` traversal are rejected. The pipeline's own logic (`runner.py`, `utils/`) cannot be modified by proposals — only through direct human editing.

---

## apply_proposal.py

The human-in-the-loop review interface.

### Usage

```bash
# Review the most recent pending proposal
python apply_proposal.py

# Review a specific proposal
python apply_proposal.py proposals/2026-03-22T143000.json

# List all proposals (pending and applied)
python apply_proposal.py --list

# Preview without applying
python apply_proposal.py --dry-run

# Apply all without prompting (use with care)
python apply_proposal.py --auto-apply
```

### Review flow

For each proposal, you are shown:
- The title and type
- The rationale (why this change is proposed)
- The list of operations (which files, what size)

You choose one of:
- `[a]pply` — apply the operations for this proposal
- `[r]eject` — reject with an optional reason
- `[v]iew` — see the full file diff, then decide

After reviewing all proposals, approved operations are written to disk, `EVOLUTION.md` is updated, and a git commit is made.

### Rejection reasons

When you reject a proposal, you can provide a reason. This is stored in the proposal JSON and written to `EVOLUTION.md`. The reason is useful context for future post-mortems — the Opus model can see what was rejected and why, avoiding repeating the same proposals.

---

## EVOLUTION.md

A human-readable changelog of all self-improvements. Updated automatically by `apply_proposal.py` after each review session.

### Format

```markdown
---

## 2026-03-22 — Run `2026-03-22T130000`

**Post-mortem Quality Assessment:** fair

**Issues Identified:**
- Requirements agent missed non-functional requirements
- TDD Green required 4 retries on a simple feature

**Proposals Applied: 2/3**

### ✅ Improve Requirements Agent Prompt
*Type: `update_agent` | Priority: `high` | Files: agents/01_requirements.md*

Added an explicit Non-Functional Requirements section to the requirements prompt...

### ✅ Reduce TDD Green Max Attempts and Add Better Error Context
*Type: `update_pipeline` | Priority: `medium` | Files: pipeline.json*

Changed tdd_green_max_attempts from 5 to 3 and improved the retry message format...

### ❌ Add Security Review Step *(Rejected)*
*Type: `add_step` | Priority: `low`*

*Rejection reason: Not needed for this project scope*
```

---

## Git audit trail

Every applied self-improvement creates a git commit:

```
[self-improve] Run 2026-03-22T130000: 2 improvement(s) applied

Types: update_agent, update_pipeline
Changes:
- Improve Requirements Agent Prompt
- Reduce TDD Green Max Attempts and Add Better Error Context

1 proposal(s) rejected.
See EVOLUTION.md for full details.
```

### Querying the history

```bash
# All self-improvement commits
git log --grep="\[self-improve\]" --oneline

# What changed in a specific improvement
git show abc1234

# Diff between now and before all self-improvements
git diff $(git log --grep="\[self-improve\]" --format="%H" | tail -1)~1 HEAD -- agents/

# Roll back a specific improvement
git revert abc1234
```

---

## Running postmortem standalone

If you skipped the post-mortem during a run, or want to re-analyse an older run:

```bash
# Most recent run
python postmortem.py

# Specific run
python postmortem.py 2026-03-22T143000

# List runs available for analysis
python postmortem.py --list
```

---

## Safety mechanisms

| Mechanism | How it works |
|-----------|-------------|
| Human approval required | No proposal is applied without `apply_proposal.py` being run interactively |
| Path allowlist | Proposals can only write to `agents/`, `pipeline.json`, `skills/`, `docs/`, `README.md` |
| Path traversal check | `..` and absolute paths are rejected |
| Dry run | `--apply_proposal.py --dry-run` previews changes without writing |
| Git rollback | Every applied improvement is a committed change; `git revert` undoes it |
| Rejection logging | Rejected proposals are stored with reasons, preventing repeated bad suggestions |

---

## Tips for effective self-improvement

1. **Run the pipeline on a range of features** — the post-mortem learns from patterns, not individual runs. A prompt weakness that shows up once may be noise; if it shows up on three runs, it's a real issue.

2. **Keep rejection reasons specific** — "not needed" is less useful than "this project doesn't use a database so a security review for SQL injection is irrelevant."

3. **Apply high-priority proposals first** — a weak requirements prompt will cascade into weak tests and incomplete verification. Fix upstream issues before downstream ones.

4. **Review the `view` diff carefully** — when an agent prompt is being rewritten, compare old vs new before approving. The model may have removed something important.

5. **Don't apply everything at once** — applying one proposal per session makes it easy to identify which change caused a regression if quality drops.

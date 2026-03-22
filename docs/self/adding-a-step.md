# Adding a Pipeline Step

Steps can be added manually or by the self-improvement process via `add_step` proposals. This guide covers both cases.

---

## When to add a step

Consider adding a step when you consistently see a class of issue that no existing step catches. Examples:
- Security vulnerabilities slipping through → add a Security Review step after TDD Green
- Generated code has inconsistent style → add a Linting/Style step
- Documentation is never generated → add a Docs Generation step
- Dependencies have known vulnerabilities → add a Dependency Audit step

A step should have a single, well-defined responsibility. Don't add a "catch everything" step.

---

## Step structure

A step requires two things:
1. An **agent prompt** in `agents/`
2. A **step definition** in `pipeline.json`

---

## Step 1: Write the agent prompt

Create a new file in `agents/`. Follow the naming convention: `NN_stepname.md` where `NN` is a two-digit number. Use `00` if you're inserting at the start, or a number between existing steps.

### Template

```markdown
You are a [role description]. Your job is to [one sentence description of what this step does].

## Your Task

[2-3 sentences explaining the context and purpose.]

## What You Must Produce

[Explicit list of what the output contains.]

## Rules

- [Constraint 1]
- [Constraint 2]
- [etc.]

## Workflow

1. [Step 1]
2. [Step 2]
...

## Output

[For structured steps:]
Call the `complete` tool with your structured output:
```json
{
  "output": {
    "field_1": "...",
    ...
  }
}
```

[For code-writing steps:]
Call `complete` with:
- `summary`: What you did
- `files_written`: List of paths
```

### Prompts for structured-output steps

Add this at the end of the output section:
```
Do not output prose — call `complete` directly with the structured output.
```

The runner will automatically append a Claude Code mode override when the step runs in `claude_code` mode (see `docs/execution-modes.md`).

### Prompts for code-writing steps

Add clear instructions about:
- Which directory to write to (`tests/unit/`, `src/`, etc.)
- What tools to use in which order
- The completion signal (`complete` tool)

---

## Step 2: Add to pipeline.json

Open `pipeline.json` and add a step definition to the `"steps"` array at the desired position:

```json
{
  "id": "security_review",
  "name": "Security Review",
  "description": "Review the implementation for common security vulnerabilities",
  "agent_prompt": "05b_security_review.md",
  "model": "agent",
  "writes_code": false,
  "optional": true
}
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier, used for artifact filenames and context keys |
| `name` | string | Human-readable display name |
| `description` | string | One-sentence description (shown during runs) |
| `agent_prompt` | string | Filename in `agents/` |
| `model` | `"agent"` or `"postmortem"` | Which model to use (maps to `models` in pipeline.json) |
| `writes_code` | boolean | Does this step write files to the workspace? |
| `optional` | boolean | If true, pipeline continues even if this step fails |

### Optional fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `execution_mode` | `"api"` or `"claude_code"` | global default | Override execution mode for this step only |
| `verify_fails` | boolean | false | (TDD Red) After writing, verify tests fail |
| `verify_passes` | boolean | false | (TDD Green) After writing, verify tests pass; enables retry loop |
| `run_integration` | boolean | false | (Integration) Run integration test suite after writing |
| `max_attempts` | integer | 5 | Max retry attempts for `verify_passes` steps |
| `is_postmortem` | boolean | false | Special handling: saves output as proposal file |

---

## Example: Security Review step

### `agents/05b_security_review.md`

```markdown
You are a senior security engineer performing a code review of a freshly implemented feature.

## Your Task

Review the implementation for common security vulnerabilities and produce a security assessment.

## What You Must Produce

For each vulnerability found (or confirmed absent):
1. Vulnerability type (OWASP category)
2. Severity: critical / high / medium / low / info
3. Location in code
4. Description of the risk
5. Recommended fix

Also produce an overall security rating.

## What To Check

- **Injection** — SQL, command, path traversal
- **Authentication** — JWT handling, session management, password storage
- **Sensitive data** — secrets in code, logging of PII, unencrypted storage
- **Input validation** — all user inputs validated/sanitised
- **Error handling** — error messages that leak internal details
- **Dependencies** — known vulnerable packages in requirements.txt

## Rules

- Review the actual code, not just the test results
- A passing test suite does not mean the code is secure
- Flag hardcoded secrets as critical regardless of other context

## Output

Call the `complete` tool with your structured output:

```json
{
  "output": {
    "overall_rating": "pass | conditional_pass | fail",
    "findings": [
      {
        "id": "SEC-001",
        "type": "Hardcoded secret",
        "severity": "critical",
        "location": "src/auth/jwt.py:12",
        "description": "JWT secret is hardcoded as 'secret123'",
        "recommendation": "Move to environment variable: os.getenv('JWT_SECRET')"
      }
    ],
    "summary": "string"
  }
}
```
```

### `pipeline.json` addition

Insert after `tdd_green` (step 4), before `verification` (step 5):

```json
{
  "id": "security_review",
  "name": "Security Review",
  "description": "Review implementation for security vulnerabilities before verification",
  "agent_prompt": "05b_security_review.md",
  "model": "agent",
  "writes_code": false,
  "optional": true
}
```

Note: renaming `agents/05_verification.md` is not required — the agent prompt filename is independent of the step order.

---

## Step 3: Update context building (if needed)

If your new step needs specific prior context that `ContextBuilder` doesn't currently provide, edit `utils/context.py → ContextBuilder.build_for_step()`:

```python
elif step_id == "security_review":
    parts.append(self._section("Requirements Specification", "requirements"))
    parts.append(self._section("TDD Green Results", "tdd_green"))
    parts.append(self._workspace_files_full(include_tests=False))
```

The `_section()` method pulls from `self.context[step_id]["output"]`. As long as you reference step IDs that exist, it works automatically.

---

## Step 4: Test the new step

Run the pipeline with `--skip-postmortem` to test just the new step:

```bash
python runner.py "Add user authentication" --skip-postmortem
```

Check the output in `runs/{run_id}/security_review.json`. If the step fails, check:
- The agent prompt for clarity
- The context builder for correct inputs
- The `pipeline.json` step definition for correct flags

---

## Step 5: Commit

```bash
git add agents/05b_security_review.md pipeline.json utils/context.py
git commit -m "Add security review step after TDD Green"
```

---

## Adding a step via self-improvement proposal

The post-mortem can propose `add_step` changes. A well-formed proposal includes:
1. A `write` operation for the new agent prompt file
2. A `write` operation for `pipeline.json` with the full updated content

When reviewing an `add_step` proposal, also check whether `utils/context.py` needs updating — the proposal may not include this if the post-mortem agent didn't know to include it.

---

## Removing a step

To remove a step:
1. Delete or archive the agent prompt (or leave it — unused prompts don't cause issues)
2. Remove the step from `pipeline.json`
3. (Optional) Remove the step from `utils/context.py` if it references the removed step's output

The self-improvement process can propose `remove_step` changes that include an updated `pipeline.json`.

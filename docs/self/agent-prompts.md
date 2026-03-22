# Agent Prompts

Agent system prompts live in `agents/`. Each file is a Markdown document that defines the persona, task, rules, and output format for one pipeline step.

## File naming

```
agents/
├── 01_requirements.md    ← step id: requirements
├── 02_plan.md            ← step id: plan
├── 03_tdd_red.md         ← step id: tdd_red
├── 04_tdd_green.md       ← step id: tdd_green
├── 05_verification.md    ← step id: verification
├── 06_integration.md     ← step id: integration
└── 07_postmortem.md      ← step id: postmortem
```

The filename is referenced in `pipeline.json` under `agent_prompt`.

## Template variables

The runner performs simple string substitution before sending the prompt to the model. Available variables:

| Variable | Value | Example |
|----------|-------|---------|
| `{language}` | Target language name | `python` |
| `{test_framework}` | Test framework for the language | `pytest` |
| `{file_extension}` | Source file extension | `.py` |

These are substituted in `runner.py → _load_agent_prompt()`.

## Prompt structure

All agent prompts follow this structure:

```markdown
# Role statement (one sentence)

## Your Task
What this agent does and why.

## What You Must Produce
Detailed specification of the required output.

## Rules
Constraints and quality requirements.

## [Tool-specific instructions]
Instructions for using tools (complete, write_file, run_tests, etc.)
These are overridden when running in claude_code mode.

## Output
How to submit the final result (call `complete` / output JSON block).
```

## Tool sets by step type

### Structured-output steps (Requirements, Plan, Verification)

**API mode tools:**
- `complete(output: object)` — submit the final structured JSON output

The agent reasons in natural language then calls `complete` with the result.

**Claude Code mode override:**
The `CLAUDE_CODE_STRUCTURED_ADDENDUM` (in `utils/claude_code_runner.py`) replaces the tool instructions with: "End your response with a ```json code block containing your complete structured output."

### Code-writing steps (TDD Red)

**API mode tools:**
- `write_file(path, content)` — write a file to workspace
- `read_file(path)` — read an existing workspace file
- `list_files(directory)` — list workspace files
- `complete(summary, files_written)` — signal completion

**Claude Code mode override:**
The `CLAUDE_CODE_FILES_WRITE_ADDENDUM` replaces tool instructions with: use Write/Edit/Read natively.

### Code-writing + test-running steps (TDD Green, Integration)

**API mode tools:**
- All of the above, plus:
- `run_tests(test_path?)` — execute the test suite and return structured results

**Claude Code mode override:**
The `CLAUDE_CODE_FILES_ADDENDUM` replaces tool instructions with: use Write/Edit/Bash/Read natively, and use `Bash` to run tests directly.

### Post-mortem step

**API mode tools:**
- `complete(analysis, run_summary, proposals)` — the full proposal schema

**Claude Code mode:**
Same structured-output addendum as other non-code steps.

## How execution mode affects prompts

The runner modifies the system prompt at runtime depending on the execution mode. The base prompt in `agents/*.md` should be mode-agnostic in its core logic, but it currently includes API-mode tool instructions at the bottom.

When running in `claude_code` mode, the runner appends a `## EXECUTION MODE: Claude Code (Override)` section to the prompt, which tells the agent to ignore the API tool instructions and use native Claude Code tools instead. This means you don't need separate prompts for each mode — the override section takes precedence.

See `utils/claude_code_runner.py` for the exact addenda text.

## Writing a new agent prompt

When adding a new pipeline step:

1. **State the role clearly** — One sentence at the top: "You are a senior X who does Y."

2. **Specify inputs explicitly** — List what context the agent receives (e.g., "You will receive the requirements specification and the full test suite").

3. **Define outputs precisely** — For structured steps, provide the exact JSON schema. For code steps, specify which directories to write to.

4. **Write explicit rules** — Don't assume the agent knows your constraints. State them:
   - "Do NOT modify test files"
   - "Every criterion must have at least one test"
   - "Use the exact import paths defined in the implementation plan"

5. **Describe the workflow** — For multi-step agents (TDD Green), give a numbered workflow list so the agent knows what order to perform actions.

6. **Add tool usage instructions** — Explain when to call each tool. For the `complete` tool, specify exactly what shape the output should have.

7. **Consider Claude Code mode** — If your step writes code, the `CLAUDE_CODE_FILES_ADDENDUM` will be appended automatically. If it produces structured output, `CLAUDE_CODE_STRUCTURED_ADDENDUM` will be appended. Make sure your prompt's core logic doesn't conflict with these.

## Modifying existing prompts

Prompts are plain Markdown files — edit them directly or have the self-improvement process propose changes.

To test a prompt change:
1. Edit the `.md` file in `agents/`
2. Run the pipeline: `python runner.py "your feature" --skip-postmortem`
3. Check the step output in `runs/{run_id}/{step_id}.json`
4. Iterate

Changes to agent prompts are tracked in git. The self-improvement process will also propose prompt changes as `update_agent` proposals.

## Quality checklist for prompts

- [ ] Role is stated in one sentence
- [ ] All inputs are listed
- [ ] Output format is precisely specified (schema or examples)
- [ ] Rules section covers the most important constraints
- [ ] Workflow is numbered and sequential
- [ ] `complete` tool usage is explained with example output
- [ ] Template variables `{language}` / `{test_framework}` are used where relevant
- [ ] Prompt does not contain mode-specific tool instructions in the core logic (keep those at the bottom so the override can work cleanly)

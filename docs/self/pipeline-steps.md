# Pipeline Steps

Each step is defined in `pipeline.json` and has a corresponding agent system prompt in `agents/`. This document explains what each step does, what it receives, what it produces, and what can go wrong.

---

## Step 1 — Requirements Generation

**Agent:** `agents/01_requirements.md`
**Model:** Sonnet
**Mode:** Structured output (no file writing)

### What it does
Transforms a free-form feature request into a structured specification with testable acceptance criteria.

### Input
- The raw feature request string

### Output (`requirements.json`)
```json
{
  "title": "User Authentication with JWT",
  "summary": "...",
  "acceptance_criteria": [
    { "id": "AC-001", "description": "Given a valid email/password, when login is called, then a JWT is returned", "testable": true, "category": "happy_path" }
  ],
  "non_functional_requirements": ["Passwords must be bcrypt-hashed with cost factor ≥ 12"],
  "out_of_scope": ["OAuth integration", "password reset flows"],
  "clarifying_assumptions": ["Email is the unique identifier"]
}
```

### Quality signals
- **Good:** 6–15 acceptance criteria covering happy paths, errors, and edge cases; each criterion includes "Given/When/Then" phrasing; NFRs are specific and measurable; each AC has a `verification_type` field (`unit`/`integration`/`visual`/`manual`); UI features have logic and visual ACs separated
- **Weak:** Vague criteria like "the system should be secure"; missing error conditions; no boundary values; mixing testable logic with untestable visual assertions in a single AC

### Common failure modes
- AC is too vague to write a test for → post-mortem should update the requirements prompt
- Too few ACs (missing edge cases) → verifier will find gaps later
- Conflicting ACs → plan agent may produce an incoherent architecture
- Visual/UI ACs not separated from logic ACs → TDD agent writes impossible-to-verify tests

---

## Step 2 — Implementation Plan

**Agent:** `agents/02_plan.md`
**Model:** Sonnet
**Mode:** Structured output (no file writing)

### What it does
Designs the software architecture: file structure, class/function interfaces (not implementations), dependency list, and the order in which things should be built.

### Input
- Feature request
- Requirements specification (Step 1 output)

### Output (`plan.json`)
```json
{
  "architecture_overview": "...",
  "file_structure": [
    { "path": "src/auth/jwt.py", "purpose": "JWT encoding/decoding utilities", "type": "source" }
  ],
  "components": [
    { "name": "JWTService", "file": "src/auth/jwt.py", "interface": "encode(payload: dict) -> str\ndecode(token: str) -> dict", "dependencies": [], "depended_on_by": ["AuthController"] }
  ],
  "external_dependencies": [
    { "package": "pyjwt", "version": "2.8.0", "justification": "JWT encoding/decoding" }
  ],
  "implementation_order": ["Step 1: Create src/ structure", "Step 2: JWTService ..."],
  "test_strategy": "Unit tests for each component in tests/unit/. Fixtures for test JWT tokens."
}
```

### Quality signals
- **Good:** Complete file listing (no surprises for TDD agent); interface signatures match AC requirements; test strategy maps to the AC list; includes AC traceability matrix; complexity estimate matches actual scope; NO integration test files in file_structure
- **Weak:** Vague file structure; missing `__init__.py` files; interfaces not specific enough for TDD agent to write meaningful tests; integration test files listed in file_structure (causes TDD Red to write them prematurely)

### Common failure modes
- Plan doesn't match requirements → TDD agent writes tests for the wrong things
- Missing files in structure → TDD agent writes imports that don't match
- Overly complex architecture → TDD Green takes many retries
- Integration test files in file_structure → TDD Red writes them, making the integration step redundant

---

## Step 3 — TDD Red Phase

**Agent:** `agents/03_tdd_red.md`
**Model:** Sonnet
**Mode:** Code writing (file writing, no test execution)

### What it does
Writes comprehensive failing tests that cover every acceptance criterion. Tests are written *before* any implementation exists.

### Input
- Feature request
- Requirements (Step 1)
- Implementation Plan (Step 2)
- Workspace structure (shows existing boilerplate)

### Output
- Test files written to `workspace/tests/unit/`
- Step artifact `tdd_red.json` contains file list and summary

After writing, the runner verifies that tests *fail* (as expected — the implementation doesn't exist yet).

### Quality signals
- **Good:** One test per AC, plus error/edge case tests; descriptive names (`test_ac001_login_with_valid_credentials_returns_jwt`); imports match the plan's file structure exactly; traceability headers at top of each test file; ONLY files in `tests/unit/`; skips `visual`/`manual` ACs
- **Weak:** `assert True` tests; tests that only cover the happy path; tests that happen to pass because of poor assertions; tests written in `tests/integration/` (wrong scope)

### Common failure modes
- Tests use wrong import paths → `ModuleNotFoundError` in TDD Green (acceptable — means the plan was followed)
- Tests are too weak → pass even with broken implementation
- Tests are overly specific to an implementation detail → hard to pass correctly
- Integration tests written here instead of in the integration step → makes step 6 redundant

---

## Step 4 — TDD Green + Implementation

**Agent:** `agents/04_tdd_green.md`
**Model:** Sonnet
**Mode:** Code writing + test execution, with retry loop (up to `max_attempts`)

### What it does
Implements the source code to make all tests pass. This is the most complex step — the agent has a `run_tests` tool and iterates until all tests pass (or exhausts attempts).

In API mode: the tool loop handles retries within a single conversation thread.
In Claude Code mode: each attempt is a new invocation but with full test output in the prompt.

### Input
- All prior context
- The test files (Step 3)
- Current test output (showing failures)

### Output
- Source files written to `workspace/src/`
- `tdd_green.json` contains attempt count, final test result, files written

After each attempt, the runner:
1. Installs any new dependencies
2. Runs the type checker (mypy / tsc)
3. Runs the full test suite

If all tests pass → success. Otherwise → retry with test failure output appended.

### Quality signals
- **Good:** Passes in 1–2 attempts; production-quality code; handles all edge cases; sets up dev dependencies (mypy, pytest) before implementation; implements incrementally with frequent test runs
- **Weak:** Requires 4–5 attempts; uses hacky special-casing to pass tests; ignores non-functional requirements; type checker silently fails due to missing mypy

### Common failure modes
- Agent modifies test files instead of implementation (caught by verifier)
- External dependency not added to requirements.txt
- Type errors not caught until type-check step
- Failing after max_attempts → step fails, pipeline stops (non-optional step)

### Configuration
`max_attempts` is set per-step in `pipeline.json` (default: 5). Increase if your feature is large and complex.

---

## Step 5 — Requirements Verification

**Agent:** `agents/05_verification.md`
**Model:** Opus (upgraded — this is the critical quality gate)
**Mode:** Structured output (reads workspace files, no writing — except fallback `_verification_report.json`)

### What it does
Independently verifies that every acceptance criterion from Step 1 is genuinely satisfied by the implementation. Tests passing is a necessary but not sufficient condition. The agent MUST read source code and test files before producing its report — rubber-stamping based on test results alone is not permitted.

### Input
- Requirements (Step 1)
- Implementation Plan (Step 2)
- TDD Red + Green results (Steps 3–4)
- Full workspace file contents

### Output (`verification.json`)
```json
{
  "overall_status": "pass | partial | fail",
  "criteria_results": [
    { "id": "AC-001", "status": "pass", "evidence": "AuthController.login() in src/auth/controller.py validates credentials and returns JWT", "test_coverage": "test_ac001_login_valid", "gaps": "" }
  ],
  "gaps": ["Password hashing cost factor not verified"],
  "security_observations": ["JWT secret is hardcoded — should be env var"],
  "recommendations": ["Add test for max token expiry"],
  "overall_notes": "..."
}
```

### Quality signals
- **Good:** Cites specific code locations; distinguishes between tests that pass trivially vs genuinely verify behaviour; identifies security/edge case gaps; assigns confidence scores per AC; verifies NFRs; reads source files before reporting
- **Weak:** Just mirrors the test results; doesn't read the actual code; produces empty output (now caught by `requires_output` flag); skips NFR verification

### Common failure modes
- Marks AC as "pass" because a test exists, without checking if the test is meaningful
- Misses NFRs (non-functional requirements) entirely
- Does not check error handling paths
- Produces empty output in claude_code interactive mode → now has file fallback (`_verification_report.json`)

---

## Step 6 — Integration Tests

**Agent:** `agents/06_integration.md`
**Model:** Sonnet
**Mode:** Code writing + integration test execution
**Optional:** Yes (pipeline continues even if this step fails)

### What it does
Writes end-to-end integration tests that exercise the system from its entry point, testing complete user journeys rather than isolated units. Then executes them. **Crucially, first checks for existing integration tests** and only writes new tests for uncovered scenarios — may complete with zero new files if coverage is already sufficient.

### Input
- All prior context
- Verification results (Step 5)

### Output
- Integration test files written to `workspace/tests/integration/`
- `integration.json` contains integration test results and any bugs found

### Quality signals
- **Good:** Tests full workflows (not mocked); sets up and tears down state; tests error recovery; checks for existing tests first and only writes what's missing; exercises 2+ components per test
- **Weak:** Essentially duplicates unit tests; mocks the components being integrated; writes 0 new files after spending 200+ seconds (should complete early if nothing to add)

### Common failure modes
- Setup/teardown issues (database not cleaned between tests)
- Tests that pass individually but fail when run together (state leakage)
- Tests that find real bugs — these are documented in the summary but the step still passes

---

## Step 7 — Post-mortem Analysis

**Agent:** `agents/07_postmortem.md`
**Model:** Opus
**Mode:** Structured output
**Optional:** Yes

### What it does
Analyses the complete pipeline run — quality of each step's output, process failures, prompt weaknesses, missing steps — and generates concrete proposals to improve the pipeline itself.

### Input
- Everything from all prior steps
- Step timing data
- Current pipeline config (pipeline.json + all agent prompts)

### Output
- Saved to `proposals/{run_id}.json` (not `postmortem.json`)
- Contains: analysis, run_summary (quality + key issues/successes), proposals[]

Each proposal has: type, title, rationale, priority (high/medium/low), severity (blocking/degrading/cosmetic), recurrence_likelihood (certain/likely/possible), and operations (file writes/deletes). The agent self-validates proposals before submitting (no empty operations, no file conflicts, no contradictions).

### Quality signals
- **Good:** Traces root causes rather than symptoms; provides complete file contents in operations, not just descriptions; proposals are ranked by impact
- **Weak:** Surface-level observations; proposals say "improve X" without specifying how

### Proposal types
| Type | What changes |
|------|-------------|
| `update_agent` | Rewrites an agent's system prompt |
| `update_pipeline` | Modifies pipeline.json settings |
| `add_step` | Adds a new step + agent prompt |
| `remove_step` | Removes a step from pipeline.json |
| `create_skill` | Creates a reusable skill in `skills/` |
| `update_docs` | Updates README or docs/ files |
| `other` | Anything else |

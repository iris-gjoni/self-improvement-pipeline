# Workspace Execution

This document explains how the pipeline manages generated code: how the workspace is structured, how language-specific commands are run, and how to add support for a new language.

---

## Workspace structure

Each pipeline run gets its own isolated workspace:

```
runs/2026-03-22T143000/
└── workspace/
    ├── src/                  ← source code (TDD Green writes here)
    │   └── __init__.py
    ├── tests/
    │   ├── __init__.py
    │   ├── unit/             ← unit tests (TDD Red writes here)
    │   │   └── __init__.py
    │   └── integration/      ← integration tests (Integration step writes here)
    │       └── __init__.py
    └── requirements.txt      ← Python deps (agents update this as needed)
```

TypeScript:
```
workspace/
├── src/                      ← source code
├── tests/
├── package.json
├── tsconfig.json
└── jest.config.js
```

### Initialisation

Before the pipeline runs, `runner.py → _init_workspace()` writes the boilerplate files defined in `languages.json → init_files`. These are only written if they don't already exist (safe for resumed runs).

---

## WorkspaceExecutor

`utils/executor.py → WorkspaceExecutor` is the interface between the pipeline and the workspace filesystem/shell.

### Key methods

#### `run_tests(test_path=None) → dict`

Runs the full test suite (or a specific path). Returns:

```python
{
    "passed": bool,           # True only if returncode==0 AND total>0 AND failed==0 AND errors==0
    "total": int,             # Total test count
    "passed_count": int,
    "failed_count": int,
    "error_count": int,
    "raw_output": str,        # Full test runner output
    "formatted_output": str,  # Last 4000 chars (for agent context)
    "returncode": int
}
```

The `passed` flag intentionally returns `False` if `total == 0` (no tests found). This prevents false positives.

#### `run_integration_tests() → dict`

Runs the integration-specific command from `languages.json → integration_test_command`. Same return shape as `run_tests`.

#### `run_type_check() → dict`

Runs `mypy` (Python) or `tsc --noEmit` (TypeScript). Returns:
```python
{
    "passed": bool,
    "errors": list[str],     # Error lines from output (capped at 50)
    "raw_output": str,
    "returncode": int
}
```

#### `install_dependencies() → dict`

Runs `pip install -r requirements.txt -q` or `npm install`. Called automatically:
- Before TDD Red verification
- After each TDD Green attempt
- Before integration tests

#### `write_workspace_file(path, content)` / `read_workspace_file(path)`

Safe file I/O with path validation. Rejects paths outside the workspace (no `..` traversal or absolute paths).

---

## languages.json

Defines how each language is executed. The pipeline uses this to know which commands to run.

### Python configuration

```json
{
  "python": {
    "file_extension": ".py",
    "test_framework": "pytest",
    "test_command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
    "integration_test_command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header", "tests/integration/"],
    "type_check_command": ["python", "-m", "mypy", "src/", "--ignore-missing-imports", "--no-error-summary"],
    "install_command": ["pip", "install", "-r", "requirements.txt", "-q"],
    "init_files": {
      "requirements.txt": "",
      "src/__init__.py": "",
      "tests/__init__.py": "",
      "tests/unit/__init__.py": "",
      "tests/integration/__init__.py": ""
    }
  }
}
```

### TypeScript configuration

```json
{
  "typescript": {
    "file_extension": ".ts",
    "test_framework": "jest",
    "test_command": ["npx", "jest", "--verbose", "--passWithNoTests"],
    "integration_test_command": ["npx", "jest", "--verbose", "--testPathPattern=integration"],
    "type_check_command": ["npx", "tsc", "--noEmit"],
    "install_command": ["npm", "install"],
    "init_files": {
      "package.json": "...",
      "tsconfig.json": "...",
      "jest.config.js": "..."
    }
  }
}
```

---

## Test output parsing

`WorkspaceExecutor` parses test runner output to extract structured counts. This is used to:
- Determine if TDD Red produced failing tests
- Drive the TDD Green retry loop
- Report in the run summary

### pytest parsing

Looks for `PASSED`, `FAILED`, `ERROR` strings in the verbose output, then falls back to the summary line (`5 passed, 2 failed`).

The `passed` flag is true only when: `returncode == 0 AND total > 0 AND failed_count == 0 AND error_count == 0`

### jest parsing

Parses the summary lines: `Tests: X passed, Y failed, Z total`

---

## Adding a new language

1. **Add a language entry to `languages.json`**:

```json
{
  "go": {
    "file_extension": ".go",
    "test_framework": "go test",
    "test_command": ["go", "test", "./...", "-v"],
    "integration_test_command": ["go", "test", "./tests/integration/...", "-v"],
    "type_check_command": ["go", "build", "./..."],
    "install_command": ["go", "mod", "tidy"],
    "test_file_pattern": "*_test.go",
    "test_dirs": ["tests/"],
    "source_dirs": ["internal/", "pkg/"],
    "init_files": {
      "go.mod": "module workspace\n\ngo 1.21\n",
      "main.go": "package main\n\nfunc main() {}\n"
    },
    "compile_check": "go build",
    "notes": "Use go test for all tests. Source in internal/ or pkg/. Tests alongside source as *_test.go files."
  }
}
```

2. **Add test output parsing to `utils/executor.py`**:

In `_parse_test_output()`, add a branch:
```python
elif lang == "go":
    return self._parse_go_test(returncode, raw)
```

Implement `_parse_go_test()` to extract pass/fail counts from `go test -v` output:
```
--- PASS: TestFoo (0.00s)
--- FAIL: TestBar (0.01s)
```

3. **Add language to runner.py choices**:

In `main()`:
```python
parser.add_argument("--language", choices=["python", "typescript", "javascript", "go"], ...)
```

4. **Test with a simple feature**:

```bash
python runner.py "Create a function that adds two numbers" --language go
```

---

## Dependency management

When agents write code that requires new packages, they update the dependency file:
- Python: add to `requirements.txt`
- TypeScript/JavaScript: add to `package.json → dependencies`

The runner calls `install_dependencies()` automatically at the right points. If the install fails, the runner logs a warning but continues (a common cause is an agent writing an incorrect package name).

### Python: common issues

- Agent writes a package that doesn't exist on PyPI → install fails silently, tests fail with `ModuleNotFoundError`
- Solution: the TDD Green retry loop will include the install error in the next attempt's context

### TypeScript: common issues

- Agent doesn't update `package.json` → `npm install` has nothing to install, `jest` imports fail
- Solution: check the agent's `files_written` list; if `package.json` is missing, the TDD Green retry provides the import error as context

---

## Ignored directories

These directories are excluded from file listings and workspace snapshots:

```python
{"__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", "dist", "build", ".git"}
```

This prevents noise in agent context and avoids feeding build artifacts back to agents.

---

## Execution timeouts

All subprocess calls have explicit timeouts (from `utils/executor.py`):

| Operation | Timeout |
|-----------|---------|
| `run_tests()` | 120s |
| `run_integration_tests()` | 180s |
| `run_type_check()` | 60s |
| `install_dependencies()` | 180s |

In Claude Code mode, the CLI invocation timeout is configured in `pipeline.json → claude_code.timeout_seconds` (default: 600s). This must be long enough for the agent to write files, install deps, and run tests within a single invocation.

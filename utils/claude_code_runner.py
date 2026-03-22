"""
Claude Code CLI runner.

Executes pipeline steps by invoking the `claude` CLI as a subprocess instead
of calling the Anthropic API directly. Claude Code handles file I/O and bash
execution natively, making it particularly powerful for code-writing steps.

When to use this mode vs API mode:
- claude_code mode: Ideal for code-writing steps (TDD Red/Green, Integration).
  Claude Code uses its own Write/Edit/Bash tools; no custom tool loop needed.
- api mode: Better for structured-output steps (Requirements, Plan, Verification)
  where you need predictable JSON output and tighter token control.

See docs/execution-modes.md for full comparison.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# Mode-specific prompt addenda injected by the runner at runtime
# ---------------------------------------------------------------------------

# Appended to structured-output agent prompts when running in claude_code mode.
# Overrides the "call the `complete` tool" instructions.
CLAUDE_CODE_STRUCTURED_ADDENDUM = """
---

## EXECUTION MODE: Claude Code (Override)

You are running inside the Claude Code CLI, not the Anthropic API directly.
**Ignore any instructions above about calling a `complete` tool — that tool does not exist here.**

You have access to Read, Glob, and Grep to explore the provided context files.

When you have finished your analysis, output your complete structured result as the **last code block** in your response, as valid JSON inside a ```json fence:

```json
{
  "your": "output here"
}
```

Do not output any text after this final JSON block.
"""

# Appended to code-writing agent prompts when running in claude_code mode.
# Overrides `write_file` / `run_tests` / `complete` tool instructions.
CLAUDE_CODE_FILES_ADDENDUM = """
---

## EXECUTION MODE: Claude Code (Override)

You are running inside the Claude Code CLI with full access to your native tools:
- **Write / Edit** — create or update files in the workspace
- **Bash** — run shell commands (tests, compilation, installs)
- **Read / Glob / Grep** — explore the workspace

**Ignore any instructions above about calling `write_file`, `run_tests`, or `complete` tools.**

Your working directory is the workspace. All file paths are relative to it.

### Workflow
1. Read the test files and implementation plan to understand what is needed.
2. Write implementation files using the **Write** or **Edit** tool.
3. Use **Bash** to install dependencies and run the test suite.
4. Fix any failures by editing the relevant files.
5. Repeat until all tests pass.
6. Output a brief summary when done.

### Running tests
```bash
# Python
python -m pytest -v --tb=short

# TypeScript / JavaScript
npx jest --verbose
```

### Installing dependencies
```bash
# Python
pip install -r requirements.txt -q

# Node
npm install
```

**Do NOT modify test files.** Fix only source/implementation files.
"""

# Same as above but without the test-passing requirement (for TDD Red and Integration).
CLAUDE_CODE_FILES_WRITE_ADDENDUM = """
---

## EXECUTION MODE: Claude Code (Override)

You are running inside the Claude Code CLI. You have access to Write, Edit, Read, Bash, Glob, and Grep.

**Ignore any instructions above about `write_file`, `run_tests`, or `complete` tools.**

Your working directory is the workspace. Write files using the Write/Edit tools.
Use Bash if you need to verify syntax or run a quick check.

When finished, output a brief summary of what you wrote.
"""


class ClaudeCodeRunner:
    """
    Runs pipeline agents via the Claude Code CLI (`claude --print`).

    The CLI is invoked as a subprocess. Claude Code uses its own native
    tools (Write, Edit, Read, Bash, Glob, Grep) to accomplish tasks,
    eliminating the need for our custom tool-loop.
    """

    def __init__(self, cli_config: dict):
        self.command = cli_config.get("command", "claude")
        self.timeout = cli_config.get("timeout_seconds", 600)
        self.code_tools = cli_config.get("code_tools", "Write,Edit,Read,Bash,Glob,Grep")
        self.read_only_tools = cli_config.get("read_only_tools", "Read,Glob,Grep")

    # ------------------------------------------------------------------
    # Public API (mirrors AgentRunner interface)
    # ------------------------------------------------------------------

    def run_structured(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        schema: dict | None = None,
        step_id: str = "",
        max_tokens: int = 8192,
    ) -> dict:
        """
        Run an agent that produces structured JSON output.
        Returns the parsed JSON dict from the response.
        """
        augmented_system = system_prompt + CLAUDE_CODE_STRUCTURED_ADDENDUM
        full_prompt = self._combine(augmented_system, user_message)

        output = self._invoke(
            prompt=full_prompt,
            cwd=None,
            tools=self.read_only_tools,
            model=model,
        )
        return self._extract_json(output)

    def run_with_files(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        workspace: Path,
        executor,
        can_run_tests: bool = False,
        max_tokens: int = 8192,
    ) -> dict:
        """
        Run an agent that writes files. Claude Code does this natively.
        Returns summary + list of files written.
        """
        addendum = CLAUDE_CODE_FILES_WRITE_ADDENDUM
        augmented_system = system_prompt + addendum
        full_prompt = self._combine(augmented_system, user_message)

        files_before = self._snapshot(workspace)
        output = self._invoke(
            prompt=full_prompt,
            cwd=workspace,
            tools=self.code_tools,
            model=model,
        )
        files_after = self._snapshot(workspace)
        new_files = sorted(set(files_after) - set(files_before))

        return {"summary": output, "files_written": new_files}

    def run_with_files_stateful(
        self,
        system_prompt: str,
        user_message: str | None,
        retry_message: str | None,
        messages: list | None,  # ignored — Claude Code is stateless per invocation
        model: str,
        workspace: Path,
        executor,
        can_run_tests: bool = False,
        max_tokens: int = 8192,
    ) -> tuple[dict, list]:
        """
        Run an agent with files. For retries, the test output is concatenated
        into the prompt so Claude Code has full context in a single invocation.

        Returns (result_dict, []) — empty messages list (no state to preserve).
        """
        addendum = CLAUDE_CODE_FILES_ADDENDUM if can_run_tests else CLAUDE_CODE_FILES_WRITE_ADDENDUM
        augmented_system = system_prompt + addendum

        # Combine base message and any retry context
        combined_user = user_message or ""
        if retry_message:
            combined_user = (combined_user + "\n\n" + retry_message).strip()

        full_prompt = self._combine(augmented_system, combined_user)
        files_before = self._snapshot(workspace)

        output = self._invoke(
            prompt=full_prompt,
            cwd=workspace,
            tools=self.code_tools,
            model=model,
        )

        files_after = self._snapshot(workspace)
        new_files = sorted(set(files_after) - set(files_before))
        result = {"summary": output, "files_written": new_files}
        return result, []  # No message state to return

    def run_postmortem(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 16000,
    ) -> dict:
        """Run the post-mortem (structured output, no file writing)."""
        augmented_system = system_prompt + CLAUDE_CODE_STRUCTURED_ADDENDUM
        full_prompt = self._combine(augmented_system, user_message)

        output = self._invoke(
            prompt=full_prompt,
            cwd=None,
            tools=self.read_only_tools,
            model=model,
        )
        return self._extract_json(output)

    # ------------------------------------------------------------------
    # CLI invocation
    # ------------------------------------------------------------------

    def _invoke(
        self,
        prompt: str,
        cwd: Path | None,
        tools: str,
        model: str,
    ) -> str:
        """Invoke `claude --print` and return the text result."""
        cmd = [
            self.command,
            "--print",
            "-p", prompt,
            "--allowedTools", tools,
            "--output-format", "json",
            "--model", model,
        ]

        console.print(f"    [dim]  -> claude CLI ({tools})[/dim]")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude Code CLI not found. Is `{self.command}` installed and on PATH? "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Claude Code CLI timed out after {self.timeout}s. "
                "Consider increasing 'claude_code.timeout_seconds' in pipeline.json."
            )

        if proc.returncode != 0:
            stderr = (proc.stderr or "")[:600]
            stdout = (proc.stdout or "")[:200]
            raise RuntimeError(
                f"Claude Code CLI exited with code {proc.returncode}.\n"
                f"stderr: {stderr}\nstdout: {stdout}"
            )

        # The JSON output has shape: {type, subtype, cost_usd, duration_ms, result, session_id, ...}
        raw = proc.stdout.strip()
        try:
            payload = json.loads(raw)
            return payload.get("result", raw)
        except json.JSONDecodeError:
            # Fallback: return raw stdout
            return raw

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _combine(system: str, user: str) -> str:
        """
        Combine system and user content into a single prompt string.
        The Claude Code CLI does not have a separate --system-prompt flag,
        so we embed the system instructions inline.
        """
        return f"<system_instructions>\n{system.strip()}\n</system_instructions>\n\n{user.strip()}"

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        Extract the last ```json ... ``` block from a response string.
        Falls back to scanning for the last top-level { ... } object.
        """
        # Find all ```json blocks
        blocks = list(re.finditer(r"```json\s*\n(.*?)\n```", text, re.DOTALL))
        if blocks:
            last = blocks[-1].group(1).strip()
            try:
                return json.loads(last)
            except json.JSONDecodeError:
                pass

        # Fallback: find the last balanced { ... }
        last_brace = text.rfind("{")
        if last_brace != -1:
            # Find matching closing brace
            depth = 0
            for i in range(last_brace, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[last_brace : i + 1])
                        except json.JSONDecodeError:
                            break

        return {
            "summary": text,
            "_parse_error": "Could not extract JSON from Claude Code response",
        }

    @staticmethod
    def _snapshot(workspace: Path) -> list[str]:
        """Return sorted list of relative file paths in workspace (ignoring caches)."""
        if not workspace.exists():
            return []
        ignored = {"__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", "dist", "build"}
        files = []
        for p in workspace.rglob("*"):
            if p.is_file() and not any(part in ignored for part in p.parts):
                files.append(str(p.relative_to(workspace)).replace("\\", "/"))
        return sorted(files)

    @staticmethod
    def check_available(command: str = "claude") -> tuple[bool, str]:
        """
        Check whether the Claude Code CLI is available and return its version.
        Returns (available: bool, message: str).
        """
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                return True, f"Claude Code CLI available: {version}"
            return False, f"CLI returned exit code {result.returncode}"
        except FileNotFoundError:
            return False, f"Command not found: '{command}'. Install with: npm install -g @anthropic-ai/claude-code"
        except Exception as e:
            return False, str(e)

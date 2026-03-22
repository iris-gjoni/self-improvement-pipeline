"""
Interactive Claude Code runner.

Launches `claude` as a live interactive terminal session instead of headless
`--print` mode. The user can converse with and guide each step. After the
session ends the runner captures structured output (for analysis steps) or
file changes (for code-writing steps) and returns the same result shape as
AgentRunner and ClaudeCodeRunner.

Interface contract (mirrors AgentRunner / ClaudeCodeRunner):
  run_structured(...)          -> dict
  run_with_files(...)          -> dict
  run_with_files_stateful(...) -> tuple[dict, list]
  run_postmortem(...)          -> dict
"""

import json
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

# ---------------------------------------------------------------------------
# Instruction addenda — injected at the bottom of each task file
# ---------------------------------------------------------------------------

INTERACTIVE_STRUCTURED_ADDENDUM = """
---

## EXECUTION MODE: Interactive Session

You are running in an interactive terminal session as part of an automated
pipeline. Take your time, read the context above, and think through your
analysis carefully.

**When you are done**, write your complete structured output as valid JSON to
the file `_step_output.json` using the Write tool. The pipeline will read
this file after you end your session.

The JSON structure must match the schema described in the system instructions
above.

End the session with `/exit` when finished.
"""

INTERACTIVE_FILES_ADDENDUM = """
---

## EXECUTION MODE: Interactive Session

You are running in an interactive terminal session in the project workspace.
You have full access to Write, Edit, Read, Bash, Glob, and Grep.

Work as you normally would. When you are finished making changes, type
`/exit` to end the session. The pipeline will detect which files you created
or modified.
"""

INTERACTIVE_POSTMORTEM_ADDENDUM = """
---

## EXECUTION MODE: Interactive Session

Analyse the full pipeline run using the context files in this directory.
When done, write your complete analysis to `_step_output.json` using the
Write tool. End the session with `/exit`.
"""


class InteractiveRunner:
    """
    Runs pipeline agents as live interactive Claude Code terminal sessions.

    Satisfies the same 4-method interface as AgentRunner and ClaudeCodeRunner
    so PipelineRunner._runner() can return any of the three transparently.

    Task context (system prompt + user message) is written to a markdown file
    in run_dir and loaded via --add-dir to avoid Windows command-line length
    limits with very large prompts.
    """

    def __init__(self, run_dir: Path, cli_config: dict):
        self.run_dir = run_dir
        self.command = cli_config.get("command", "claude")
        self.code_tools = cli_config.get("code_tools", "Write,Edit,Read,Bash,Glob,Grep")
        self.read_only_tools = cli_config.get("read_only_tools", "Read,Glob,Grep")

    # ------------------------------------------------------------------
    # Public interface (matches AgentRunner / ClaudeCodeRunner)
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
        Run a structured-output step interactively.
        Instructs Claude to write _step_output.json; reads it after session ends.
        """
        task_file = self._write_task_file(
            step_id=step_id or "structured",
            system_prompt=system_prompt,
            user_message=user_message,
            addendum=INTERACTIVE_STRUCTURED_ADDENDUM,
        )
        output_file = self.run_dir / "_step_output.json"
        if output_file.exists():
            output_file.unlink()

        short_msg = (
            f"Read your task instructions from `{task_file.name}` "
            f"(it is in the run directory that has been added as context). "
            f"Follow all instructions in that file."
        )
        self._launch_session(
            short_message=short_msg,
            model=model,
            add_dirs=[self.run_dir],
            allowed_tools=f"{self.read_only_tools},Write",
        )

        return self._read_step_output(output_file, fallback_key="output")

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
        Run a code-writing step interactively.
        Snapshots workspace before/after to detect changed files.
        """
        result, _ = self.run_with_files_stateful(
            system_prompt=system_prompt,
            user_message=user_message,
            retry_message=None,
            messages=None,
            model=model,
            workspace=workspace,
            executor=executor,
            can_run_tests=can_run_tests,
            max_tokens=max_tokens,
        )
        return result

    def run_with_files_stateful(
        self,
        system_prompt: str,
        user_message: str | None,
        retry_message: str | None,
        messages: list | None,
        model: str,
        workspace: Path,
        executor,
        can_run_tests: bool = False,
        max_tokens: int = 8192,
        step_id_hint: str = "step",
    ) -> tuple[dict, list]:
        """
        Run a code-writing step interactively (stateful variant for TDD Green retries).

        On first call: launches a session with the full task.
        On retry calls: the retry_message (test output) is appended to the task
        file so the user can see what still needs fixing.

        Returns (result_dict, []) — no message state preserved between sessions.
        """
        combined_user = user_message or ""
        if retry_message:
            combined_user = (combined_user + "\n\n" + retry_message).strip()

        task_file = self._write_task_file(
            step_id=step_id_hint,
            system_prompt=system_prompt,
            user_message=combined_user,
            addendum=INTERACTIVE_FILES_ADDENDUM,
        )
        short_msg = (
            f"Read your task instructions from `{task_file.name}` "
            f"(in the run directory). The workspace and run directory have "
            f"both been added as context directories."
        )
        files_before = _snapshot(workspace)

        self._launch_session(
            short_message=short_msg,
            model=model,
            add_dirs=[workspace, self.run_dir],
            allowed_tools=self.code_tools,
        )

        files_after = _snapshot(workspace)
        new_and_changed = sorted(set(files_after) - set(files_before))

        result = {
            "summary": "(interactive session — see workspace for changes)",
            "files_written": new_and_changed,
        }
        return result, []

    def run_postmortem(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 16000,
    ) -> dict:
        """Run the post-mortem step interactively (structured output to file)."""
        task_file = self._write_task_file(
            step_id="postmortem",
            system_prompt=system_prompt,
            user_message=user_message,
            addendum=INTERACTIVE_POSTMORTEM_ADDENDUM,
        )
        output_file = self.run_dir / "_step_output.json"
        if output_file.exists():
            output_file.unlink()

        short_msg = (
            f"Read your post-mortem task from `{task_file.name}` "
            f"(in the run directory)."
        )
        self._launch_session(
            short_message=short_msg,
            model=model,
            add_dirs=[self.run_dir],
            allowed_tools=f"{self.read_only_tools},Write",
        )

        return self._read_step_output(output_file, fallback_key="analysis")

    # ------------------------------------------------------------------
    # TDD Green retry prompt (called by PipelineRunner._run_tdd_green)
    # ------------------------------------------------------------------

    def prompt_retry_or_skip(self, attempt: int, max_attempts: int, test_result: dict) -> str:
        """
        Print test failure summary and prompt the user whether to retry.
        Returns 'retry' or 'skip'.
        Called by PipelineRunner._run_tdd_green when tests still fail after a session.
        """
        output_preview = (test_result.get("formatted_output") or "")[-2000:]
        console.print(
            Panel(
                f"Tests still failing after attempt {attempt}/{max_attempts}.\n\n"
                f"Passed:  {test_result.get('passed_count', 0)}\n"
                f"Failed:  {test_result.get('failed_count', 0)}\n"
                f"Errors:  {test_result.get('error_count', 0)}\n\n"
                f"```\n{output_preview}\n```",
                title="[yellow]TDD Green — Tests Still Failing[/yellow]",
                border_style="yellow",
            )
        )
        if attempt >= max_attempts:
            return "skip"
        while True:
            try:
                choice = console.input(
                    "[yellow]\\[r]etry (launch another session) / "
                    "[s]kip (accept partial result): [/yellow]"
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "skip"
            if choice in ("r", "retry"):
                return "retry"
            if choice in ("s", "skip"):
                return "skip"
            console.print("[dim]Please enter 'r' or 's'.[/dim]")

    # ------------------------------------------------------------------
    # Session launch
    # ------------------------------------------------------------------

    def _launch_session(
        self,
        short_message: str,
        model: str,
        add_dirs: list[Path],
        allowed_tools: str,
    ) -> None:
        """
        Launch `claude` as a live interactive subprocess.
        Blocks until the user ends the session (/exit or Ctrl+D).
        Inherits stdin/stdout/stderr from the parent process.
        """
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Interactive mode requires a real terminal (stdin is not a tty). "
                "Use --mode api or --mode claude_code instead."
            )

        cmd = [self.command]
        for d in add_dirs:
            if d and d.exists():
                cmd += ["--add-dir", str(d)]
        cmd += ["--allowedTools", allowed_tools]
        cmd += ["--model", model]
        cmd += [short_message]

        console.print(f"  [dim]-> claude interactive (model: {model}, tools: {allowed_tools})[/dim]")
        console.print(f"  [dim]   Type /exit when done.[/dim]")
        console.print()

        try:
            proc = subprocess.run(
                cmd,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude Code CLI not found: '{self.command}'. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Session interrupted.[/yellow]")
            return

        console.print()
        if proc.returncode not in (0, 130):  # 130 = SIGINT/Ctrl+C
            console.print(
                f"[yellow]Warning: claude exited with code {proc.returncode}[/yellow]"
            )

    # ------------------------------------------------------------------
    # Task file writer
    # ------------------------------------------------------------------

    def _write_task_file(
        self,
        step_id: str,
        system_prompt: str,
        user_message: str,
        addendum: str,
    ) -> Path:
        """
        Write system prompt + user message + addendum to a markdown file in run_dir.
        Returns the Path of the written file.

        Writing to a file instead of passing via command-line argument avoids
        Windows CreateProcess command-line length limits (~32 KB) for large contexts.
        """
        content = (
            f"<system_instructions>\n{system_prompt.strip()}\n</system_instructions>\n\n"
            f"{user_message.strip()}\n\n"
            f"{addendum.strip()}\n"
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        task_file = self.run_dir / f"_task_{step_id}.md"
        task_file.write_text(content, encoding="utf-8")
        return task_file

    # ------------------------------------------------------------------
    # Step output reader
    # ------------------------------------------------------------------

    def _read_step_output(self, output_file: Path, fallback_key: str) -> dict:
        """
        Read and parse _step_output.json written by Claude during the session.
        Falls back gracefully if the file is missing, empty, or malformed.
        """
        if not output_file.exists() or output_file.stat().st_size == 0:
            console.print(
                f"[yellow]Warning: Claude did not write {output_file.name}. "
                f"Returning empty result.[/yellow]"
            )
            return {fallback_key: "", "_interactive_missing_output": True}

        try:
            data = json.loads(output_file.read_text(encoding="utf-8"))
            output_file.unlink()  # Clean up
            return data
        except json.JSONDecodeError as e:
            raw = output_file.read_text(encoding="utf-8")
            console.print(
                f"[yellow]Warning: {output_file.name} is not valid JSON ({e}). "
                f"Storing raw content.[/yellow]"
            )
            return {fallback_key: raw, "_interactive_parse_error": str(e)}


# ---------------------------------------------------------------------------
# Workspace snapshot helper
# ---------------------------------------------------------------------------

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

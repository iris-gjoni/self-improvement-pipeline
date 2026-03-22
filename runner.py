#!/usr/bin/env python3
"""
Self-Improving Software Development Pipeline Runner

Supports two usage modes:

  NEW PROJECT (creates a fresh codebase from scratch):
    python runner.py "Build a REST API for todo items" --project-name todo-api
    python runner.py "Add user authentication" --language typescript

  EXISTING PROJECT (adds features to or maintains an existing codebase):
    python runner.py "Add password reset flow" --project-dir /path/to/project
    python runner.py "Fix the login bug" --project-dir /path/to/project --project-name my-app

  OTHER:
    python runner.py --resume 2026-03-22T143000     # Resume an interrupted run
    python runner.py --list-runs                    # List all previous runs
    python runner.py --list-projects               # List known projects
    python runner.py --check-cli                   # Verify Claude Code CLI is available
    python runner.py "..." --mode claude_code       # Force Claude Code CLI mode
    python runner.py "..." --skip-postmortem        # Skip post-mortem analysis
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))

from utils.agent import AgentRunner
from utils.claude_code_runner import ClaudeCodeRunner
from utils.context import ContextBuilder
from utils.executor import WorkspaceExecutor
from utils.logger import StepLogger
from utils.project_registry import ProjectRegistry, detect_language, slugify

console = Console()

BASE_DIR = Path(__file__).parent
RUNS_DIR = BASE_DIR / "runs"
AGENTS_DIR = BASE_DIR / "agents"
PROPOSALS_DIR = BASE_DIR / "proposals"


# ===========================================================================
# PipelineRunner
# ===========================================================================


class PipelineRunner:
    def __init__(
        self,
        feature_request: str,
        language: str | None = None,
        project_name: str | None = None,
        project_dir: Path | None = None,
        resume_run_id: str | None = None,
        skip_postmortem: bool = False,
        mode_override: str | None = None,
    ):
        self.client = anthropic.Anthropic()
        self.feature_request = feature_request
        self.skip_postmortem = skip_postmortem

        self.pipeline = self._load_json("pipeline.json")
        self.languages = self._load_json("languages.json")

        # Docs repository (configurable path, defaults to ./docs)
        docs_repo_setting = self.pipeline.get("docs_repo", "docs")
        docs_root = (
            Path(docs_repo_setting)
            if Path(docs_repo_setting).is_absolute()
            else BASE_DIR / docs_repo_setting
        )
        self.registry = ProjectRegistry(BASE_DIR / "projects.json", docs_root)

        # Execution mode: CLI flag > pipeline.json default
        self.global_mode = mode_override or self.pipeline.get("execution_mode", "api")
        self._cc_config = self.pipeline.get("claude_code", {})

        # Validate Claude Code CLI availability up front if needed
        if self.global_mode == "claude_code" or any(
            s.get("execution_mode") == "claude_code" for s in self.pipeline.get("steps", [])
        ):
            ok, msg = ClaudeCodeRunner.check_available(self._cc_config.get("command", "claude"))
            if not ok:
                console.print(f"[bold red]Claude Code CLI unavailable:[/bold red] {msg}")
                sys.exit(1)
            console.print(f"[dim]{msg}[/dim]")

        # ------------------------------------------------------------------
        # Resume
        # ------------------------------------------------------------------
        if resume_run_id:
            self.run_id = resume_run_id
            self.run_dir = RUNS_DIR / resume_run_id
            if not self.run_dir.exists():
                console.print(f"[red]Run not found: {resume_run_id}[/red]")
                sys.exit(1)
            meta = self._load_run_meta()
            self.context = meta.get("context", {})
            self.feature_request = meta.get("feature_request", feature_request)
            project_name = project_name or meta.get("project_name")
            project_dir = Path(meta["project_dir"]) if meta.get("project_dir") else project_dir
            language = language or meta.get("language", "python")
            console.print(f"[yellow]Resuming run {resume_run_id}[/yellow]")
        else:
            self.run_id = datetime.now().strftime("%Y-%m-%dT%H%M%S")
            self.run_dir = RUNS_DIR / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.context = {}

        # ------------------------------------------------------------------
        # Project resolution
        # ------------------------------------------------------------------
        self.project_dir: Path | None = Path(project_dir).resolve() if project_dir else None

        # Try to find existing project in registry
        existing = None
        if project_name:
            existing = self.registry.find(project_name)
        if existing is None and self.project_dir:
            existing = self.registry.find_by_dir(self.project_dir)

        if existing:
            # Known project
            self.project_name = existing["name"]
            self.is_new_project = False
            # Project dir from registry takes precedence unless explicitly overridden
            if self.project_dir is None and existing.get("project_dir"):
                self.project_dir = Path(existing["project_dir"])
            self.language = language or existing.get("language", "python")
        else:
            # New project — auto-name from project_name arg or feature request
            self.project_name = project_name or slugify(feature_request)
            self.is_new_project = True
            # Auto-detect language from project dir if possible
            if self.project_dir and self.project_dir.exists():
                self.language = language or detect_language(self.project_dir)
            else:
                self.language = language or "python"

        # ------------------------------------------------------------------
        # Workspace
        # ------------------------------------------------------------------
        if self.project_dir and self.project_dir.exists():
            # Existing project: workspace IS the project directory
            self.workspace = self.project_dir
        else:
            # New project: fresh workspace per run
            self.workspace = self.run_dir / "workspace"
            self.workspace.mkdir(exist_ok=True)

        # Project documentation directory
        self.project_doc_dir: Path = self.registry.get_doc_dir(self.project_name)

        # ------------------------------------------------------------------
        # Internal services
        # ------------------------------------------------------------------
        self.executor = WorkspaceExecutor(self.workspace, self.language, self.languages)
        self.logger = StepLogger(self.run_dir)
        self.agent_runner = AgentRunner(self.client, AGENTS_DIR)
        self.cc_runner = ClaudeCodeRunner(self._cc_config)

        PROPOSALS_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> dict:
        # Register or update the project
        if self.is_new_project:
            self.registry.register(
                name=self.project_name,
                project_dir=self.project_dir,
                language=self.language,
                description=self.feature_request[:200],
            )
            console.print(f"[green]New project registered:[/green] {self.project_name}")
        else:
            console.print(f"[cyan]Known project:[/cyan] {self.project_name} (continuing work)")

        run_meta = {
            "id": self.run_id,
            "feature_request": self.feature_request,
            "language": self.language,
            "project_name": self.project_name,
            "project_dir": str(self.project_dir) if self.project_dir else None,
            "is_new_project": self.is_new_project,
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "steps": {},
            "context": self.context,
        }
        self.logger.save_run_meta(run_meta)

        mode_label = self.global_mode
        project_label = (
            f"{self.project_name}  [dim](new)[/dim]"
            if self.is_new_project
            else f"{self.project_name}  [dim](existing)[/dim]"
        )
        workspace_label = str(self.workspace)

        console.print(
            Panel(
                f"[bold cyan]Run ID:[/bold cyan]       {self.run_id}\n"
                f"[bold cyan]Project:[/bold cyan]      {project_label}\n"
                f"[bold cyan]Feature:[/bold cyan]      {self.feature_request[:100]}\n"
                f"[bold cyan]Language:[/bold cyan]     {self.language}\n"
                f"[bold cyan]Mode:[/bold cyan]         {mode_label}\n"
                f"[bold cyan]Workspace:[/bold cyan]    {workspace_label}\n"
                f"[bold cyan]Project docs:[/bold cyan] {self.project_doc_dir}",
                title="[bold green]Self-Improving Development Pipeline[/bold green]",
                border_style="green",
            )
        )

        # Only init workspace for new projects / fresh workspaces
        if not self.project_dir or not self.project_dir.exists():
            self._init_workspace()

        steps = self.pipeline["steps"]
        total = len(steps)

        for i, step in enumerate(steps, 1):
            step_id = step["id"]

            if step_id in self.context and self.context[step_id].get("status") in ("success", "partial"):
                console.print(f"[dim][{i}/{total}] Skipping completed step: {step['name']}[/dim]")
                continue

            if step.get("is_postmortem") and self.skip_postmortem:
                console.print(f"[dim][{i}/{total}] Skipping post-mortem (--skip-postmortem)[/dim]")
                continue

            console.print(f"\n[bold blue][{i}/{total}] {step['name']}[/bold blue]")
            console.print(f"[dim]{step['description']}[/dim]")

            self.logger.log_event("step_start", {"step_id": step_id})
            step_start = datetime.now()

            try:
                result = self._run_step(step)
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Run state saved — resume with:[/yellow]")
                console.print(f"  python runner.py --resume {self.run_id} ...")
                run_meta["status"] = "interrupted"
                run_meta["context"] = self.context
                self.logger.save_run_meta(run_meta)
                sys.exit(0)
            except Exception as e:
                console.print_exception()
                result = {"status": "error", "error": str(e)}

            result.setdefault("status", "success")
            result["duration_seconds"] = (datetime.now() - step_start).total_seconds()

            self.context[step_id] = result
            run_meta["steps"][step_id] = {
                "status": result["status"],
                "duration_seconds": result["duration_seconds"],
                "completed_at": datetime.now().isoformat(),
            }
            run_meta["context"] = self.context
            self.logger.save_run_meta(run_meta)
            self.logger.save_step(step_id, result)
            self.logger.log_event("step_complete", {"step_id": step_id, "status": result["status"]})

            status = result["status"]
            if status == "success":
                console.print(f"[green]✓ {step['name']} — done ({result['duration_seconds']:.1f}s)[/green]")
            elif status == "partial":
                console.print(f"[yellow]⚠ {step['name']} — partial ({result['duration_seconds']:.1f}s)[/yellow]")
            elif status in ("failed", "error"):
                console.print(f"[red]✗ {step['name']} — {status}[/red]")
                if result.get("error"):
                    console.print(f"[red]  Error: {result['error']}[/red]")
                if not step.get("optional", False):
                    console.print("[red]Non-optional step failed. Stopping pipeline.[/red]")
                    break

        run_meta["status"] = "completed"
        run_meta["completed_at"] = datetime.now().isoformat()
        run_meta["context"] = self.context
        self.logger.save_run_meta(run_meta)

        # Record this run in the project registry
        self.registry.record_run(self.project_name, self.run_id)

        self._print_summary()
        return run_meta

    # ------------------------------------------------------------------
    # Step dispatch
    # ------------------------------------------------------------------

    def _step_mode(self, step: dict) -> str:
        return step.get("execution_mode") or self.global_mode

    def _runner(self, step: dict):
        return self.cc_runner if self._step_mode(step) == "claude_code" else self.agent_runner

    def _step_workspace(self, step: dict) -> Path:
        """Return the appropriate workspace for a step.

        doc_update steps write to the project's docs directory, not the code workspace.
        All other steps use the code workspace.
        """
        if step.get("doc_workspace") == "project_docs":
            self.project_doc_dir.mkdir(parents=True, exist_ok=True)
            return self.project_doc_dir
        return self.workspace

    def _run_step(self, step: dict) -> dict:
        model_key = step.get("model", "agent")
        model = self.pipeline["models"][model_key]
        max_tokens = (
            self.pipeline["execution"]["postmortem_max_tokens"]
            if step.get("is_postmortem")
            else self.pipeline["execution"]["agent_max_tokens"]
        )

        system_prompt = self._load_agent_prompt(step)
        user_message = self._build_context_message(step)
        runner = self._runner(step)
        step_ws = self._step_workspace(step)

        mode = self._step_mode(step)
        if mode != "api":
            console.print(f"  [dim]Mode: {mode}[/dim]")

        if step.get("is_postmortem"):
            return self._run_postmortem_step(step, system_prompt, model, user_message, max_tokens, runner)

        if step.get("writes_code"):
            if step.get("verify_fails"):
                return self._run_tdd_red(step, system_prompt, model, user_message, max_tokens, runner)
            elif step.get("verify_passes"):
                return self._run_tdd_green(step, system_prompt, model, user_message, max_tokens, runner)
            elif step.get("run_integration"):
                return self._run_integration(step, system_prompt, model, user_message, max_tokens, runner)
            else:
                # General file-writing step (e.g. doc_update) — uses step_ws, no test verification
                doc_executor = WorkspaceExecutor(step_ws, self.language, self.languages)
                output = runner.run_with_files(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    model=model,
                    workspace=step_ws,
                    executor=doc_executor,
                    max_tokens=max_tokens,
                )
                return {"status": "success", "output": output}
        else:
            output = runner.run_structured(
                system_prompt=system_prompt,
                user_message=user_message,
                model=model,
                schema=None,
                step_id=step["id"],
                max_tokens=max_tokens,
            )
            return {"status": "success", "output": output}

    # ------------------------------------------------------------------
    # TDD Red
    # ------------------------------------------------------------------

    def _run_tdd_red(self, step, system_prompt, model, user_message, max_tokens, runner) -> dict:
        output = runner.run_with_files(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            workspace=self.workspace,
            executor=self.executor,
            can_run_tests=False,
            max_tokens=max_tokens,
        )

        install_result = self.executor.install_dependencies()
        if not install_result["success"]:
            console.print(f"  [yellow]Dependency install warning: {install_result['output'][:200]}[/yellow]")

        test_result = self.executor.run_tests()
        total = test_result["total"]
        failed = test_result["failed_count"] + test_result["error_count"]

        if total == 0:
            console.print("  [yellow]Warning: No tests found in workspace.[/yellow]")
        elif test_result["passed"] and failed == 0:
            console.print("  [yellow]Warning: All tests passing — TDD Red expects them to FAIL.[/yellow]")
        else:
            console.print(f"  [green]✓ TDD Red: {total} test(s) failing as expected[/green]")

        return {
            "status": "success",
            "output": output,
            "test_result": test_result,
            "files_written": output.get("files_written", []),
        }

    # ------------------------------------------------------------------
    # TDD Green
    # ------------------------------------------------------------------

    def _run_tdd_green(self, step, system_prompt, model, user_message, max_tokens, runner) -> dict:
        max_attempts = step.get(
            "max_attempts", self.pipeline["execution"]["tdd_green_max_attempts"]
        )

        self.executor.install_dependencies()
        test_result = self.executor.run_tests()
        messages = None
        all_files_written: list[str] = []

        for attempt in range(1, max_attempts + 1):
            console.print(f"  [dim]Attempt {attempt}/{max_attempts}[/dim]")

            if attempt == 1:
                augmented_message = (
                    user_message
                    + f"\n\n## Current Test Output (All Failing)\n\n```\n{test_result['formatted_output']}\n```"
                )
                retry_msg = None
            else:
                augmented_message = None
                retry_msg = (
                    f"Tests still failing (attempt {attempt}/{max_attempts}).\n\n"
                    f"**Current:** {test_result['passed_count']} passed, "
                    f"{test_result['failed_count']} failed, {test_result['error_count']} errors\n\n"
                    f"```\n{test_result['formatted_output']}\n```\n\n"
                    f"Fix the remaining failures. Do NOT modify test files."
                )

            output, messages = runner.run_with_files_stateful(
                system_prompt=system_prompt,
                user_message=augmented_message,
                retry_message=retry_msg,
                messages=messages,
                model=model,
                workspace=self.workspace,
                executor=self.executor,
                can_run_tests=True,
                max_tokens=max_tokens,
            )

            all_files_written.extend(output.get("files_written", []))
            self.executor.install_dependencies()

            type_result = self.executor.run_type_check()
            if type_result.get("errors"):
                console.print(f"  [yellow]Type errors: {len(type_result['errors'])}[/yellow]")

            test_result = self.executor.run_tests()
            console.print(
                f"  [dim]Tests: {test_result['passed_count']}/{test_result['total']} passed, "
                f"{test_result['failed_count']} failed, {test_result['error_count']} errors[/dim]"
            )

            all_passing = (
                test_result["passed"]
                and test_result["total"] > 0
                and test_result["failed_count"] == 0
                and test_result["error_count"] == 0
                and not type_result.get("errors")
            )

            if all_passing:
                console.print(f"  [green]✓ All {test_result['total']} tests passing![/green]")
                return {
                    "status": "success",
                    "attempts": attempt,
                    "test_result": test_result,
                    "type_result": type_result,
                    "files_written": list(set(all_files_written)),
                }

        console.print(f"  [red]TDD Green failed after {max_attempts} attempts[/red]")
        return {
            "status": "failed",
            "attempts": max_attempts,
            "test_result": test_result,
            "files_written": list(set(all_files_written)),
            "error": f"Could not make all tests pass in {max_attempts} attempts.",
        }

    # ------------------------------------------------------------------
    # Integration Tests
    # ------------------------------------------------------------------

    def _run_integration(self, step, system_prompt, model, user_message, max_tokens, runner) -> dict:
        output, _ = runner.run_with_files_stateful(
            system_prompt=system_prompt,
            user_message=user_message,
            retry_message=None,
            messages=None,
            model=model,
            workspace=self.workspace,
            executor=self.executor,
            can_run_tests=True,
            max_tokens=max_tokens,
        )

        self.executor.install_dependencies()
        integration_result = self.executor.run_integration_tests()

        console.print(
            f"  Integration tests: {integration_result['passed_count']}/{integration_result['total']} passed, "
            f"{integration_result['failed_count']} failed"
        )

        status = "success" if integration_result["passed"] or integration_result["failed_count"] == 0 else "partial"
        return {
            "status": status,
            "output": output,
            "integration_result": integration_result,
            "files_written": output.get("files_written", []),
        }

    # ------------------------------------------------------------------
    # Post-mortem
    # ------------------------------------------------------------------

    def _run_postmortem_step(self, step, system_prompt, model, user_message, max_tokens, runner) -> dict:
        console.print("  [dim]Running Opus post-mortem analysis...[/dim]")

        result = runner.run_postmortem(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            max_tokens=max_tokens,
        )

        proposal = {
            "id": self.run_id,
            "run_id": self.run_id,
            "project_name": self.project_name,
            "generated_at": datetime.now().isoformat(),
            "status": "pending",
            "analysis": result.get("analysis", ""),
            "run_summary": result.get("run_summary", {}),
            "proposals": result.get("proposals", []),
        }

        proposal_path = PROPOSALS_DIR / f"{self.run_id}.json"
        proposal_path.write_text(json.dumps(proposal, indent=2))

        n = len(proposal.get("proposals", []))
        console.print(f"  [green]✓ Post-mortem complete: {n} proposal(s)[/green]")
        console.print(f"  [dim]python apply_proposal.py {proposal_path}[/dim]")

        return {
            "status": "success",
            "output": result,
            "proposal_path": str(proposal_path),
            "proposal_count": n,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _init_workspace(self) -> None:
        """Write language boilerplate to a fresh workspace. Safe on existing projects (skips existing files)."""
        lang_config = self.languages.get(self.language, {})
        for rel_path, content in lang_config.get("init_files", {}).items():
            target = self.workspace / rel_path
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

    def _load_agent_prompt(self, step: dict) -> str:
        prompt_file = AGENTS_DIR / step["agent_prompt"]
        prompt = prompt_file.read_text(encoding="utf-8")
        lang_config = self.languages.get(self.language, {})
        prompt = prompt.replace("{language}", self.language)
        prompt = prompt.replace("{test_framework}", lang_config.get("test_framework", "pytest"))
        prompt = prompt.replace("{file_extension}", lang_config.get("file_extension", ".py"))
        return prompt

    def _build_context_message(self, step: dict) -> str:
        builder = ContextBuilder(
            context=self.context,
            workspace=self.workspace,
            feature_request=self.feature_request,
            language=self.language,
            project_name=self.project_name,
            is_new_project=self.is_new_project,
            project_doc_dir=self.project_doc_dir,
            registry=self.registry,
        )
        return builder.build_for_step(step)

    def _load_json(self, filename: str) -> dict:
        return json.loads((BASE_DIR / filename).read_text(encoding="utf-8"))

    def _load_run_meta(self) -> dict:
        path = self.run_dir / "run.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _print_summary(self) -> None:
        table = Table(title=f"Pipeline Summary — {self.project_name} / {self.run_id}", border_style="blue")
        table.add_column("Step", style="cyan", min_width=28)
        table.add_column("Status", style="bold", min_width=10)
        table.add_column("Duration", style="dim", min_width=8)
        table.add_column("Notes", style="dim")

        for step in self.pipeline["steps"]:
            step_id = step["id"]
            if step_id not in self.context:
                table.add_row(step["name"], "[dim]skipped[/dim]", "-", "")
                continue

            result = self.context[step_id]
            status = result.get("status", "unknown")
            duration = f"{result.get('duration_seconds', 0):.1f}s"
            notes = ""

            if step_id == "tdd_green" and "attempts" in result:
                notes = f"{result['attempts']} attempt(s)"
            if step_id in ("tdd_green", "tdd_red") and "test_result" in result:
                tr = result["test_result"]
                notes = f"{tr.get('passed_count', 0)}/{tr.get('total', 0)} tests"
            if step_id == "postmortem" and "proposal_count" in result:
                notes = f"{result['proposal_count']} proposal(s)"
            if step_id == "doc_update":
                out = result.get("output", {})
                written = out.get("files_written", [])
                notes = f"{len(written)} doc file(s)"

            color = {"success": "green", "partial": "yellow", "failed": "red", "error": "red"}.get(
                status, "dim"
            )
            table.add_row(step["name"], f"[{color}]{status}[/{color}]", duration, notes)

        console.print("\n")
        console.print(table)
        console.print(f"\n[dim]Run artifacts:  {self.run_dir}[/dim]")
        console.print(f"[dim]Project docs:   {self.project_doc_dir}[/dim]")

        postmortem = self.context.get("postmortem", {})
        if postmortem.get("proposal_path"):
            console.print(
                f"\n[bold yellow]Post-mortem proposals ready:[/bold yellow]\n"
                f"  python apply_proposal.py {postmortem['proposal_path']}"
            )


# ===========================================================================
# CLI
# ===========================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Self-improving software development pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "feature_request",
        nargs="?",
        help="Feature request, bug description, or maintenance task",
    )
    parser.add_argument(
        "--project-name",
        metavar="NAME",
        help="Project identifier. Auto-generated from feature request if not provided.",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        help=(
            "Path to an existing project directory to work on. "
            "When provided, the pipeline maintains existing code rather than creating from scratch."
        ),
    )
    parser.add_argument(
        "--language",
        "-l",
        choices=["python", "typescript", "javascript"],
        default=None,
        help="Target language. Auto-detected from project dir if not provided.",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["api", "claude_code"],
        default=None,
        help="Override execution mode for all steps ('api' or 'claude_code').",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume an interrupted pipeline run by its run ID.",
    )
    parser.add_argument(
        "--skip-postmortem",
        action="store_true",
        help="Skip the post-mortem analysis step.",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List all previous pipeline runs.",
    )
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List all known projects in the registry.",
    )
    parser.add_argument(
        "--check-cli",
        action="store_true",
        help="Check whether the Claude Code CLI is installed and available.",
    )

    args = parser.parse_args()

    if args.check_cli:
        pipeline = json.loads((BASE_DIR / "pipeline.json").read_text())
        cmd = pipeline.get("claude_code", {}).get("command", "claude")
        ok, msg = ClaudeCodeRunner.check_available(cmd)
        console.print(f"{'[green]✓[/green]' if ok else '[red]✗[/red]'} {msg}")
        sys.exit(0 if ok else 1)

    if args.list_runs:
        _list_runs()
        return

    if args.list_projects:
        _list_projects()
        return

    if not args.feature_request and not args.resume:
        parser.print_help()
        sys.exit(1)

    project_dir = Path(args.project_dir) if args.project_dir else None

    runner = PipelineRunner(
        feature_request=args.feature_request or "",
        language=args.language,
        project_name=args.project_name,
        project_dir=project_dir,
        resume_run_id=args.resume,
        skip_postmortem=args.skip_postmortem,
        mode_override=args.mode,
    )
    runner.run()


def _list_runs() -> None:
    runs_dir = BASE_DIR / "runs"
    if not runs_dir.exists() or not any(runs_dir.iterdir()):
        console.print("[dim]No runs found.[/dim]")
        return

    table = Table(title="Previous Runs", border_style="blue")
    table.add_column("Run ID", style="cyan")
    table.add_column("Project", style="bold")
    table.add_column("Status")
    table.add_column("Feature Request", style="dim", max_width=55)
    table.add_column("Lang")

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        meta_file = run_dir / "run.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            status = meta.get("status", "unknown")
            color = {"completed": "green", "interrupted": "yellow", "running": "blue"}.get(status, "dim")
            table.add_row(
                meta.get("id", run_dir.name),
                meta.get("project_name", "—"),
                f"[{color}]{status}[/{color}]",
                meta.get("feature_request", "")[:55],
                meta.get("language", "?"),
            )
        except Exception:
            table.add_row(run_dir.name, "?", "[dim]?[/dim]", "", "")

    console.print(table)


def _list_projects() -> None:
    pipeline = json.loads((BASE_DIR / "pipeline.json").read_text())
    docs_repo_setting = pipeline.get("docs_repo", "docs")
    docs_root = (
        Path(docs_repo_setting)
        if Path(docs_repo_setting).is_absolute()
        else BASE_DIR / docs_repo_setting
    )
    registry = ProjectRegistry(BASE_DIR / "projects.json", docs_root)
    projects = registry.all()

    if not projects:
        console.print("[dim]No projects registered yet.[/dim]")
        console.print("[dim]Run the pipeline to register a project:[/dim]")
        console.print("  python runner.py 'Your feature request' --project-name my-project")
        return

    table = Table(title="Known Projects", border_style="blue")
    table.add_column("Name", style="cyan")
    table.add_column("Language")
    table.add_column("Runs", style="dim")
    table.add_column("Last Run", style="dim")
    table.add_column("Project Dir", style="dim", max_width=45)

    for p in sorted(projects, key=lambda x: x.get("last_run_at") or "", reverse=True):
        last_run = (p.get("last_run_at") or "never")[:19]
        project_dir = p.get("project_dir") or "[dim]new[/dim]"
        table.add_row(
            p["name"],
            p.get("language", "?"),
            str(len(p.get("runs", []))),
            last_run,
            project_dir,
        )

    console.print(table)


if __name__ == "__main__":
    main()

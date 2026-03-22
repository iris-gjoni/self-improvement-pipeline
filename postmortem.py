#!/usr/bin/env python3
"""
Standalone post-mortem runner.

Run a post-mortem analysis on any completed pipeline run, producing
a proposal file for review with apply_proposal.py.

Usage:
    python postmortem.py                          # Analyse most recent run
    python postmortem.py 2026-03-22T143000        # Analyse specific run
    python postmortem.py --list                   # List available runs
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent))

from utils.agent import AgentRunner
from utils.context import ContextBuilder
from utils.logger import StepLogger

console = Console()

BASE_DIR = Path(__file__).parent
RUNS_DIR = BASE_DIR / "runs"
AGENTS_DIR = BASE_DIR / "agents"
PROPOSALS_DIR = BASE_DIR / "proposals"


def run_postmortem(run_id: str) -> str:
    """Run post-mortem on a completed pipeline run. Returns path to proposal file."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        console.print(f"[red]Run not found: {run_id}[/red]")
        sys.exit(1)

    logger = StepLogger(run_dir)
    meta = logger.load_run_meta()
    if not meta:
        console.print(f"[red]No run.json found in {run_dir}[/red]")
        sys.exit(1)

    console.print(
        Panel(
            f"[bold cyan]Run:[/bold cyan] {run_id}\n"
            f"[bold cyan]Feature:[/bold cyan] {meta.get('feature_request', '?')[:120]}\n"
            f"[bold cyan]Language:[/bold cyan] {meta.get('language', '?')}",
            title="[bold yellow]Post-mortem Analysis[/bold yellow]",
            border_style="yellow",
        )
    )

    # Load pipeline config
    pipeline = json.loads((BASE_DIR / "pipeline.json").read_text())
    languages = json.loads((BASE_DIR / "languages.json").read_text())

    # Find postmortem step config
    postmortem_step = next(
        (s for s in pipeline["steps"] if s.get("is_postmortem")), None
    )
    if not postmortem_step:
        console.print("[red]No postmortem step defined in pipeline.json[/red]")
        sys.exit(1)

    model = pipeline["models"][postmortem_step.get("model", "postmortem")]
    max_tokens = pipeline["execution"]["postmortem_max_tokens"]

    # Load agent prompt
    prompt_file = AGENTS_DIR / postmortem_step["agent_prompt"]
    system_prompt = prompt_file.read_text(encoding="utf-8")
    lang = meta.get("language", "python")
    lang_config = languages.get(lang, {})
    system_prompt = system_prompt.replace("{language}", lang)
    system_prompt = system_prompt.replace("{test_framework}", lang_config.get("test_framework", "pytest"))

    # Build context from run artifacts
    workspace = run_dir / "workspace"
    context = meta.get("context", {})
    feature_request = meta.get("feature_request", "")

    builder = ContextBuilder(
        context=context,
        workspace=workspace,
        feature_request=feature_request,
        language=lang,
    )
    user_message = builder.build_for_step(postmortem_step)

    # Add run timing metadata
    steps_summary = []
    for step_id, step_meta in meta.get("steps", {}).items():
        steps_summary.append(
            f"- {step_id}: {step_meta.get('status', '?')} "
            f"({step_meta.get('duration_seconds', 0):.1f}s)"
        )
    if steps_summary:
        user_message += "\n\n## Step Timing Summary\n\n" + "\n".join(steps_summary) + "\n"

    # Run agent
    client = anthropic.Anthropic()
    agent_runner = AgentRunner(client, AGENTS_DIR)

    console.print("[dim]Sending to Opus for analysis...[/dim]")
    result = agent_runner.run_postmortem(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=max_tokens,
    )

    # Save proposal
    PROPOSALS_DIR.mkdir(exist_ok=True)
    proposal = {
        "id": run_id,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(),
        "status": "pending",
        "analysis": result.get("analysis", ""),
        "run_summary": result.get("run_summary", {}),
        "proposals": result.get("proposals", []),
    }

    proposal_path = PROPOSALS_DIR / f"{run_id}.json"
    proposal_path.write_text(json.dumps(proposal, indent=2))

    n = len(proposal.get("proposals", []))
    quality = proposal.get("run_summary", {}).get("overall_quality", "?")
    console.print(f"\n[green]OK Post-mortem complete[/green]")
    console.print(f"  Overall quality: [bold]{quality}[/bold]")
    console.print(f"  Proposals generated: [bold]{n}[/bold]")
    console.print(f"\n  Review proposals:\n    [cyan]python apply_proposal.py {proposal_path}[/cyan]")

    return str(proposal_path)


def list_runs() -> None:
    if not RUNS_DIR.exists():
        console.print("[dim]No runs found.[/dim]")
        return

    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        meta_file = run_dir / "run.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            has_postmortem = (PROPOSALS_DIR / f"{run_dir.name}.json").exists()
            runs.append({
                "id": run_dir.name,
                "status": meta.get("status", "?"),
                "feature": meta.get("feature_request", "?")[:70],
                "has_postmortem": has_postmortem,
            })
        except Exception:
            pass

    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return

    from rich.table import Table
    table = Table(title="Available Runs", border_style="blue")
    table.add_column("Run ID", style="cyan")
    table.add_column("Status")
    table.add_column("Post-mortem")
    table.add_column("Feature Request", style="dim", max_width=70)

    for r in runs:
        pm = "[green]done[/green]" if r["has_postmortem"] else "[dim]pending[/dim]"
        color = {"completed": "green", "interrupted": "yellow"}.get(r["status"], "dim")
        table.add_row(r["id"], f"[{color}]{r['status']}[/{color}]", pm, r["feature"])

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Run post-mortem analysis on a pipeline run")
    parser.add_argument("run_id", nargs="?", help="Run ID to analyse (default: most recent)")
    parser.add_argument("--list", action="store_true", help="List available runs")
    args = parser.parse_args()

    if args.list:
        list_runs()
        return

    if args.run_id:
        run_id = args.run_id
    else:
        # Find most recent completed run
        if not RUNS_DIR.exists() or not any(RUNS_DIR.iterdir()):
            console.print("[red]No runs found. Run the pipeline first.[/red]")
            sys.exit(1)
        candidates = sorted(
            (d for d in RUNS_DIR.iterdir() if (d / "run.json").exists()),
            reverse=True,
        )
        if not candidates:
            console.print("[red]No runs with run.json found.[/red]")
            sys.exit(1)
        run_id = candidates[0].name
        console.print(f"[dim]Using most recent run: {run_id}[/dim]")

    run_postmortem(run_id)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Interactive proposal review and application tool.

Reviews post-mortem proposals, lets you approve or reject each one,
applies approved changes, and commits them to git.

Usage:
    python apply_proposal.py                              # Review most recent pending proposal
    python apply_proposal.py proposals/2026-03-22T...json # Review specific proposal
    python apply_proposal.py --list                       # List all proposals
    python apply_proposal.py --auto-apply                 # Apply all proposals without prompting
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

console = Console()

BASE_DIR = Path(__file__).parent
PROPOSALS_DIR = BASE_DIR / "proposals"
EVOLUTION_MD = BASE_DIR / "EVOLUTION.md"

# Paths that proposals are allowed to write to (no path traversal)
ALLOWED_PATH_PREFIXES = [
    "agents/",
    "pipeline.json",
    "languages.json",
    "skills/",
    "EVOLUTION.md",
    "README.md",
    "docs/self/",   # pipeline self-documentation
    "docs/",        # also allow bare docs/ for backwards compat
]


# ===========================================================================
# Main
# ===========================================================================


def main():
    parser = argparse.ArgumentParser(description="Review and apply post-mortem proposals")
    parser.add_argument("proposal_path", nargs="?", help="Path to proposal JSON file")
    parser.add_argument("--list", action="store_true", help="List all proposals")
    parser.add_argument(
        "--auto-apply",
        action="store_true",
        help="Apply all proposals without interactive prompting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be applied without making changes",
    )
    args = parser.parse_args()

    if args.list:
        list_proposals()
        return

    # Find proposal to review
    if args.proposal_path:
        proposal_path = Path(args.proposal_path)
    else:
        proposal_path = _find_most_recent_pending()
        if not proposal_path:
            console.print("[yellow]No pending proposals found.[/yellow]")
            console.print("Run the pipeline first: python runner.py 'Your feature request'")
            sys.exit(0)

    if not proposal_path.exists():
        console.print(f"[red]Proposal not found: {proposal_path}[/red]")
        sys.exit(1)

    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    apply_proposal(proposal, proposal_path, auto_apply=args.auto_apply, dry_run=args.dry_run)


# ===========================================================================
# Core application logic
# ===========================================================================


def apply_proposal(
    proposal: dict,
    proposal_path: Path,
    auto_apply: bool = False,
    dry_run: bool = False,
) -> None:
    run_id = proposal.get("run_id", "?")
    proposals = proposal.get("proposals", [])
    run_summary = proposal.get("run_summary", {})

    # Header
    quality = run_summary.get("overall_quality", "?")
    quality_color = {"excellent": "green", "good": "cyan", "fair": "yellow", "poor": "red"}.get(
        quality, "dim"
    )
    console.print(
        Panel(
            f"[bold]Run:[/bold] {run_id}\n"
            f"[bold]Generated:[/bold] {proposal.get('generated_at', '?')}\n"
            f"[bold]Overall Quality:[/bold] [{quality_color}]{quality}[/{quality_color}]\n"
            f"[bold]Proposals:[/bold] {len(proposals)}",
            title="[bold yellow]Post-mortem Proposals[/bold yellow]",
            border_style="yellow",
        )
    )

    # Analysis summary
    analysis = proposal.get("analysis", "")
    if analysis:
        console.print("\n[bold]Analysis Summary[/bold]")
        # Print first 800 chars of analysis
        excerpt = analysis[:800] + ("..." if len(analysis) > 800 else "")
        console.print(Markdown(excerpt))

    if run_summary.get("key_issues"):
        console.print("\n[bold red]Key Issues:[/bold red]")
        for issue in run_summary["key_issues"]:
            console.print(f"  • {issue}")

    if run_summary.get("key_successes"):
        console.print("\n[bold green]Key Successes:[/bold green]")
        for s in run_summary["key_successes"]:
            console.print(f"  • {s}")

    if not proposals:
        console.print("\n[dim]No proposals in this post-mortem.[/dim]")
        return

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_proposals = sorted(
        proposals, key=lambda p: priority_order.get(p.get("priority", "low"), 2)
    )

    # Review each proposal
    approved: list[dict] = []
    rejected: list[dict] = []
    rejection_reasons: dict[str, str] = {}

    console.print(f"\n[bold]Reviewing {len(sorted_proposals)} proposal(s)[/bold]\n")

    for idx, prop in enumerate(sorted_proposals, 1):
        prop_id = prop.get("id", f"prop_{idx}")
        prop_type = prop.get("type", "other")
        title = prop.get("title", "Untitled")
        rationale = prop.get("rationale", "")
        priority = prop.get("priority", "medium")
        operations = prop.get("operations", [])

        priority_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(priority, "dim")

        console.print(
            Panel(
                f"[bold]{title}[/bold]\n"
                f"[dim]Type:[/dim] {prop_type}  "
                f"[dim]Priority:[/dim] [{priority_color}]{priority}[/{priority_color}]  "
                f"[dim]Operations:[/dim] {len(operations)}\n\n"
                f"[italic]{rationale}[/italic]",
                title=f"[cyan]Proposal {idx}/{len(sorted_proposals)}[/cyan]",
                border_style="cyan",
            )
        )

        # Show operations
        _show_operations(operations)

        # Validate all operations
        errors = _validate_operations(operations)
        if errors:
            console.print("[red]⚠ Validation errors:[/red]")
            for e in errors:
                console.print(f"  [red]• {e}[/red]")

        if auto_apply and not errors:
            console.print("[dim]Auto-applying...[/dim]")
            approved.append(prop)
        elif dry_run:
            console.print("[dim](dry-run — no changes made)[/dim]")
        elif errors:
            console.print("[yellow]Proposal has validation errors — rejecting automatically.[/yellow]")
            rejected.append(prop)
            rejection_reasons[prop_id] = "validation errors: " + "; ".join(errors)
        else:
            action = _prompt_action()
            if action == "apply":
                approved.append(prop)
            elif action == "reject":
                reason = Prompt.ask("  Reason for rejection (optional)", default="")
                rejected.append(prop)
                rejection_reasons[prop_id] = reason
            elif action == "view":
                _show_full_diff(operations)
                # Ask again after viewing
                if Confirm.ask("Apply this proposal?", default=True):
                    approved.append(prop)
                else:
                    reason = Prompt.ask("  Reason for rejection (optional)", default="")
                    rejected.append(prop)
                    rejection_reasons[prop_id] = reason

        console.print()

    # Apply approved proposals
    if not approved:
        console.print("[yellow]No proposals approved. No changes made.[/yellow]")
        _update_proposal_status(proposal, proposal_path, approved, rejected, rejection_reasons)
        return

    console.print(f"\n[bold]Applying {len(approved)} approved proposal(s)...[/bold]")

    if dry_run:
        console.print("[dim]Dry run — not applying changes.[/dim]")
        return

    apply_errors: list[str] = []
    for prop in approved:
        try:
            _apply_operations(prop.get("operations", []))
            console.print(f"  [green]✓ Applied: {prop.get('title')}[/green]")
        except Exception as e:
            console.print(f"  [red]✗ Failed to apply '{prop.get('title')}': {e}[/red]")
            apply_errors.append(str(e))
            rejected.append(prop)
            approved.remove(prop)

    # Update EVOLUTION.md
    _update_evolution_md(run_id, proposal, approved, rejected, rejection_reasons)

    # Update proposal status
    _update_proposal_status(proposal, proposal_path, approved, rejected, rejection_reasons)

    # Git commit
    _git_commit(run_id, approved, rejected)

    # Summary
    console.print(
        Panel(
            f"[green]Applied:[/green] {len(approved)} proposal(s)\n"
            f"[yellow]Rejected:[/yellow] {len(rejected)} proposal(s)\n"
            + (f"[red]Errors:[/red] {len(apply_errors)}\n" if apply_errors else ""),
            title="[bold green]Done[/bold green]",
            border_style="green",
        )
    )


# ===========================================================================
# Operations
# ===========================================================================


def _apply_operations(operations: list[dict]) -> None:
    for op in operations:
        action = op["action"]
        path = op["path"]
        content = op.get("content", "")

        # Security: validate path
        _assert_safe_path(path)

        target = BASE_DIR / path

        if action == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        elif action == "append":
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
        elif action == "delete":
            if target.exists():
                target.unlink()
        else:
            raise ValueError(f"Unknown action: {action}")


def _validate_operations(operations: list[dict]) -> list[str]:
    errors = []
    for i, op in enumerate(operations):
        action = op.get("action")
        path = op.get("path", "")

        if action not in ("write", "append", "delete"):
            errors.append(f"Op {i+1}: unknown action '{action}'")
            continue

        if not path:
            errors.append(f"Op {i+1}: missing path")
            continue

        try:
            _assert_safe_path(path)
        except ValueError as e:
            errors.append(f"Op {i+1}: {e}")

        if action in ("write", "append") and "content" not in op:
            errors.append(f"Op {i+1}: '{action}' requires 'content'")

    return errors


def _assert_safe_path(path: str) -> None:
    if path.startswith("/") or "\\" in path:
        raise ValueError(f"Absolute paths not allowed: {path}")
    if ".." in path.split("/"):
        raise ValueError(f"Path traversal not allowed: {path}")
    if not any(path.startswith(p) or path == p for p in ALLOWED_PATH_PREFIXES):
        raise ValueError(
            f"Path '{path}' is not in an allowed location. "
            f"Allowed: {', '.join(ALLOWED_PATH_PREFIXES)}"
        )


# ===========================================================================
# EVOLUTION.md
# ===========================================================================


def _update_evolution_md(
    run_id: str,
    proposal: dict,
    approved: list[dict],
    rejected: list[dict],
    rejection_reasons: dict,
) -> None:
    run_summary = proposal.get("run_summary", {})
    quality = run_summary.get("overall_quality", "?")
    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")

    lines = [
        f"\n---\n",
        f"## {date_str} — Run `{run_id}`\n",
        f"**Post-mortem Quality Assessment:** {quality}\n",
    ]

    if run_summary.get("key_issues"):
        lines.append("**Issues Identified:**\n")
        for issue in run_summary["key_issues"]:
            lines.append(f"- {issue}\n")

    if run_summary.get("key_successes"):
        lines.append("\n**Successes:**\n")
        for s in run_summary["key_successes"]:
            lines.append(f"- {s}\n")

    lines.append(
        f"\n**Proposals Applied: {len(approved)}/{len(approved) + len(rejected)}**\n\n"
    )

    for prop in approved:
        prop_type = prop.get("type", "other")
        title = prop.get("title", "?")
        rationale = prop.get("rationale", "")
        ops = prop.get("operations", [])
        files = [op["path"] for op in ops]
        lines.append(f"### ✅ {title}\n")
        lines.append(f"*Type: `{prop_type}` | Priority: `{prop.get('priority', '?')}` | Files: {', '.join(files)}*\n\n")
        lines.append(f"{rationale}\n\n")

    for prop in rejected:
        prop_id = prop.get("id", "?")
        title = prop.get("title", "?")
        prop_type = prop.get("type", "other")
        reason = rejection_reasons.get(prop_id, "")
        lines.append(f"### ❌ {title} *(Rejected)*\n")
        lines.append(f"*Type: `{prop_type}` | Priority: `{prop.get('priority', '?')}`*\n\n")
        if reason:
            lines.append(f"*Rejection reason: {reason}*\n\n")

    entry = "".join(lines)

    if EVOLUTION_MD.exists():
        existing = EVOLUTION_MD.read_text(encoding="utf-8")
        EVOLUTION_MD.write_text(existing + entry, encoding="utf-8")
    else:
        EVOLUTION_MD.write_text("# Pipeline Evolution\n\nThis document tracks all self-improvements made to the pipeline.\n" + entry, encoding="utf-8")


# ===========================================================================
# Git integration
# ===========================================================================


def _git_commit(run_id: str, approved: list[dict], rejected: list[dict]) -> None:
    if not approved:
        return

    # Check if we're in a git repo
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("[dim]Not a git repository — skipping commit.[/dim]")
        return

    # Stage changed files
    changed_files: list[str] = ["EVOLUTION.md"]
    for prop in approved:
        for op in prop.get("operations", []):
            path = op.get("path", "")
            if path and op["action"] != "delete":
                changed_files.append(path)
            elif path and op["action"] == "delete":
                changed_files.append(path)

    for f in set(changed_files):
        subprocess.run(["git", "add", f], cwd=BASE_DIR, capture_output=True)

    titles = [p.get("title", "?") for p in approved]
    types = list(set(p.get("type", "other") for p in approved))
    commit_msg = (
        f"[self-improve] Run {run_id}: {len(approved)} improvement(s) applied\n\n"
        f"Types: {', '.join(types)}\n"
        f"Changes:\n"
        + "\n".join(f"- {t}" for t in titles)
        + f"\n\n{len(rejected)} proposal(s) rejected.\n"
        f"See EVOLUTION.md for full details."
    )

    result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        # Get commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
        )
        commit_hash = hash_result.stdout.strip()
        console.print(f"[green]✓ Committed: {commit_hash}[/green]")
        console.print(f"  [dim]git show {commit_hash}[/dim]")
    else:
        console.print(f"[yellow]Git commit failed: {result.stderr}[/yellow]")
        console.print("[dim]Changes were written to disk but not committed.[/dim]")


# ===========================================================================
# Proposal status
# ===========================================================================


def _update_proposal_status(
    proposal: dict,
    proposal_path: Path,
    approved: list[dict],
    rejected: list[dict],
    rejection_reasons: dict,
) -> None:
    approved_ids = {p["id"] for p in approved}
    rejected_ids = {p["id"] for p in rejected}

    for prop in proposal.get("proposals", []):
        prop_id = prop.get("id")
        if prop_id in approved_ids:
            prop["applied"] = True
            prop["applied_at"] = datetime.now().isoformat()
        elif prop_id in rejected_ids:
            prop["rejected"] = True
            prop["rejection_reason"] = rejection_reasons.get(prop_id, "")

    proposal["status"] = "applied" if approved else "rejected"
    proposal["reviewed_at"] = datetime.now().isoformat()
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")


# ===========================================================================
# Display helpers
# ===========================================================================


def _show_operations(operations: list[dict]) -> None:
    if not operations:
        console.print("  [dim]No operations[/dim]")
        return

    for op in operations:
        action = op.get("action", "?")
        path = op.get("path", "?")
        content = op.get("content", "")
        size = f"{len(content):,} chars" if content else ""
        action_color = {"write": "green", "append": "cyan", "delete": "red"}.get(action, "dim")
        console.print(f"  [{action_color}]{action}[/{action_color}] {path}  [dim]{size}[/dim]")


def _show_full_diff(operations: list[dict]) -> None:
    for op in operations:
        action = op.get("action", "?")
        path = op.get("path", "?")
        content = op.get("content", "")

        console.print(f"\n[bold]--- {action}: {path} ---[/bold]")

        if action == "delete":
            console.print("[red]File will be deleted.[/red]")
            continue

        if not content:
            console.print("[dim](empty content)[/dim]")
            continue

        # Try to detect language for syntax highlighting
        ext = Path(path).suffix.lstrip(".")
        lang_map = {
            "py": "python",
            "ts": "typescript",
            "js": "javascript",
            "json": "json",
            "md": "markdown",
        }
        lang = lang_map.get(ext, "text")

        # Show existing file if it exists
        existing_path = BASE_DIR / path
        if existing_path.exists():
            console.print("[dim](existing file — will be replaced)[/dim]")

        console.print(Syntax(content[:3000] + ("..." if len(content) > 3000 else ""), lang))


def _prompt_action() -> str:
    while True:
        choice = Prompt.ask(
            "  [bold]Action[/bold]",
            choices=["apply", "reject", "view", "a", "r", "v"],
            default="apply",
        )
        if choice in ("a", "apply"):
            return "apply"
        if choice in ("r", "reject"):
            return "reject"
        if choice in ("v", "view"):
            return "view"


def list_proposals() -> None:
    if not PROPOSALS_DIR.exists() or not any(PROPOSALS_DIR.glob("*.json")):
        console.print("[dim]No proposals found.[/dim]")
        return

    table = Table(title="Proposals", border_style="blue")
    table.add_column("Run ID", style="cyan")
    table.add_column("Generated")
    table.add_column("Status")
    table.add_column("Quality")
    table.add_column("Proposals")

    for p in sorted(PROPOSALS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text())
            status = data.get("status", "pending")
            color = {"applied": "green", "pending": "yellow", "rejected": "red"}.get(status, "dim")
            quality = data.get("run_summary", {}).get("overall_quality", "?")
            n = len(data.get("proposals", []))
            table.add_row(
                data.get("run_id", p.stem),
                data.get("generated_at", "?")[:19],
                f"[{color}]{status}[/{color}]",
                quality,
                str(n),
            )
        except Exception:
            table.add_row(p.stem, "?", "[red]error[/red]", "?", "?")

    console.print(table)


def _find_most_recent_pending() -> Path | None:
    if not PROPOSALS_DIR.exists():
        return None
    candidates = sorted(PROPOSALS_DIR.glob("*.json"), reverse=True)
    for p in candidates:
        try:
            data = json.loads(p.read_text())
            if data.get("status") == "pending":
                return p
        except Exception:
            pass
    return None


if __name__ == "__main__":
    main()

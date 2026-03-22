"""Build context messages for each pipeline step from accumulated run state."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.project_registry import ProjectRegistry

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Average English text: ~4 chars per token for Claude.
# Code is denser (~3.5 chars/token). We use 3.5 as a conservative estimate
# so we overcount slightly rather than blow past the context window.
CHARS_PER_TOKEN = 3.5

# Default token budget for context messages. This leaves room for the system
# prompt (~2K tokens) and the model's output (max_tokens) within the 200K window.
# Individual steps can override via max_context_tokens parameter.
DEFAULT_MAX_CONTEXT_TOKENS = 80_000


def estimate_tokens(text: str) -> int:
    """Estimate token count from a string. Conservative (overestimates slightly)."""
    return int(len(text) / CHARS_PER_TOKEN)


class ContextBuilder:
    def __init__(
        self,
        context: dict,
        workspace: Path,
        feature_request: str,
        language: str,
        project_name: str = "",
        is_new_project: bool = True,
        project_doc_dir: Path | None = None,
        registry: "ProjectRegistry | None" = None,
    ):
        self.context = context
        self.workspace = workspace
        self.feature_request = feature_request
        self.language = language
        self.project_name = project_name
        self.is_new_project = is_new_project
        self.project_doc_dir = project_doc_dir
        self.registry = registry

    def build_for_step(self, step: dict, max_context_tokens: int | None = None) -> str:
        token_budget = max_context_tokens or DEFAULT_MAX_CONTEXT_TOKENS
        step_id = step["id"]
        parts: list[str] = []

        # --- Universal header ---
        parts.append(self._project_header())

        # --- Step-specific context ---
        if step_id == "requirements":
            if not self.is_new_project:
                parts.append(self._existing_project_context())
            # Requirements is the first substantive step — no prior step outputs

        elif step_id == "plan":
            if not self.is_new_project:
                parts.append(self._existing_project_context())
            parts.append(self._section("Requirements Specification", "requirements"))

        elif step_id == "tdd_red":
            if not self.is_new_project:
                parts.append(self._existing_tests_notice())
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._workspace_structure())

        elif step_id == "tdd_green":
            if not self.is_new_project:
                parts.append(self._existing_code_notice())
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._workspace_files_full(include_tests=True, token_budget=token_budget))

        elif step_id == "verification":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._section("TDD Red Results", "tdd_red"))
            parts.append(self._section("TDD Green Results", "tdd_green"))
            parts.append(self._workspace_files_full(include_tests=True, token_budget=token_budget))

        elif step_id == "integration":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._section("TDD Green Results", "tdd_green"))
            parts.append(self._section("Verification Results", "verification"))
            parts.append(self._workspace_files_full(include_tests=False, token_budget=token_budget))

        elif step_id == "postmortem":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._section("TDD Red Results", "tdd_red"))
            parts.append(self._section("TDD Green Results", "tdd_green"))
            parts.append(self._section("Verification Results", "verification"))
            parts.append(self._section("Integration Test Results", "integration"))
            parts.append(self._workspace_structure())
            parts.append(self._pipeline_config())

        elif step_id == "doc_update":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Verification Results", "verification"))
            parts.append(self._workspace_structure())
            parts.append(self._existing_project_docs())

        result = "\n".join(p for p in parts if p.strip())

        # Enforce overall token budget
        estimated = estimate_tokens(result)
        if estimated > token_budget:
            result = self._trim_to_budget(result, token_budget)

        return result

    # ------------------------------------------------------------------
    # Header and project identity
    # ------------------------------------------------------------------

    def _project_header(self) -> str:
        mode = "new project" if self.is_new_project else "existing project (maintenance/feature addition)"
        parts = [
            f"## Project\n",
            f"**Name:** {self.project_name or '(unnamed)'}",
            f"**Mode:** {mode}",
            f"**Language:** {self.language}",
            f"",
            f"## Feature Request\n",
            self.feature_request,
            "",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Existing project notices
    # ------------------------------------------------------------------

    def _existing_project_context(self) -> str:
        """Context for Requirements and Plan steps on existing projects."""
        parts = [
            "## Existing Project Context\n",
            "This is an **existing project**. You are adding a new feature or making changes to existing code.",
            "Review the current codebase structure and any existing documentation before proceeding.\n",
        ]

        # Existing docs
        if self.registry and self.project_name:
            existing_docs = self.registry.existing_docs(self.project_name)
            if existing_docs:
                parts.append("### Existing Project Documentation\n")
                for filename, content in existing_docs.items():
                    preview = content[:2000] + ("..." if len(content) > 2000 else "")
                    parts.append(f"#### `{filename}`\n\n{preview}\n")

        # Current workspace structure
        parts.append(self._workspace_structure())

        return "\n".join(parts)

    def _existing_tests_notice(self) -> str:
        """Notice for TDD Red on existing projects."""
        return (
            "## Important: Existing Project\n\n"
            "This project already has code and tests. When writing new tests:\n"
            "- Do NOT overwrite existing test files\n"
            "- Write NEW test files for the new feature only\n"
            "- Follow the existing test structure and naming conventions\n"
            "- Your new tests must not break any existing tests\n"
        )

    def _existing_code_notice(self) -> str:
        """Notice for TDD Green on existing projects."""
        return (
            "## Important: Existing Project\n\n"
            "This project already has code. When implementing:\n"
            "- Modify existing files where appropriate, or add new ones\n"
            "- Do NOT break existing functionality — all pre-existing tests must still pass\n"
            "- Follow the existing code style and architecture\n"
            "- Use `list_files` to understand the existing structure before writing\n"
        )

    # ------------------------------------------------------------------
    # Step output sections
    # ------------------------------------------------------------------

    def _section(self, title: str, step_id: str) -> str:
        data = self.context.get(step_id)
        if not data:
            return f"## {title}\n\n_Not available._\n"
        output = data.get("output", data)
        try:
            text = json.dumps(output, indent=2, default=str)
        except Exception:
            text = str(output)
        return f"## {title}\n\n```json\n{text}\n```\n"

    # ------------------------------------------------------------------
    # Workspace sections
    # ------------------------------------------------------------------

    def _workspace_structure(self) -> str:
        if not self.workspace or not self.workspace.exists():
            return ""
        files = []
        for p in sorted(self.workspace.rglob("*")):
            if p.is_file() and not self._is_ignored(p):
                rel = str(p.relative_to(self.workspace)).replace("\\", "/")
                files.append(f"  {rel}")
        if not files:
            return "## Workspace\n\n_Empty workspace._\n"
        listing = "\n".join(files)
        return f"## Workspace File Structure\n\n```\n{listing}\n```\n"

    def _workspace_files_full(self, include_tests: bool = True, token_budget: int = DEFAULT_MAX_CONTEXT_TOKENS) -> str:
        if not self.workspace or not self.workspace.exists():
            return ""

        # Collect all eligible files with their sizes
        eligible: list[tuple[Path, int]] = []
        for p in sorted(self.workspace.rglob("*")):
            if not p.is_file() or self._is_ignored(p):
                continue
            rel = str(p.relative_to(self.workspace)).replace("\\", "/")
            if not include_tests and "test" in rel.lower():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            eligible.append((p, size))

        if not eligible:
            return ""

        # Budget: reserve ~40% of total token budget for workspace files.
        # The rest is for step outputs, headers, etc.
        workspace_token_budget = int(token_budget * 0.4)
        workspace_char_budget = int(workspace_token_budget * CHARS_PER_TOKEN)

        # Per-file cap: distribute budget, but cap individual files
        per_file_char_cap = min(6000, max(2000, workspace_char_budget // max(len(eligible), 1)))

        parts = ["## Workspace Files\n"]
        chars_used = 0
        files_included = 0
        files_skipped = 0

        for p, size in eligible:
            rel = str(p.relative_to(self.workspace)).replace("\\", "/")

            # Check if we're approaching the budget
            if chars_used > workspace_char_budget:
                files_skipped += 1
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > per_file_char_cap:
                    content = content[:per_file_char_cap] + f"\n... [truncated — {len(content):,} chars total]"
                file_block = f"### `{rel}`\n\n```\n{content}\n```\n"
                chars_used += len(file_block)
                parts.append(file_block)
                files_included += 1
            except Exception:
                parts.append(f"### `{rel}`\n\n_[could not read file]_\n")

        if files_skipped > 0:
            parts.append(
                f"\n_[Context truncated: {files_skipped} file(s) omitted to stay within token budget. "
                f"Use `read_file` or `list_files` to explore the full workspace.]_\n"
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Project documentation sections
    # ------------------------------------------------------------------

    def _existing_project_docs(self) -> str:
        """Include existing project docs for the doc_update step."""
        if not self.registry or not self.project_name:
            return ""
        existing = self.registry.existing_docs(self.project_name)
        if not existing:
            project_type = "new" if self.is_new_project else "existing"
            return (
                f"## Existing Project Documentation\n\n"
                f"_No documentation exists yet for project `{self.project_name}`. "
                f"This is a {project_type} project — create documentation from scratch._\n"
            )
        parts = [
            f"## Existing Project Documentation\n\n"
            f"The following documentation already exists for project `{self.project_name}`. "
            f"Update it to reflect the new feature.\n"
        ]
        for filename, content in existing.items():
            preview = content[:3000] + ("..." if len(content) > 3000 else "")
            parts.append(f"### `{filename}`\n\n```markdown\n{preview}\n```\n")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Pipeline config (for post-mortem)
    # ------------------------------------------------------------------

    def _pipeline_config(self) -> str:
        # Resolve pipeline root reliably: walk up from workspace until we find pipeline.json
        pipeline_path = None
        agents_path = None
        search = self.workspace
        for _ in range(8):
            candidate = search / "pipeline.json"
            if candidate.exists():
                pipeline_path = candidate
                agents_path = search / "agents"
                break
            parent = search.parent
            if parent == search:
                break  # filesystem root
            search = parent

        parts = ["## Current Pipeline Configuration\n"]

        if pipeline_path and pipeline_path.exists():
            content = pipeline_path.read_text()
            parts.append(f"### pipeline.json\n\n```json\n{content}\n```\n")

        if agents_path and agents_path.exists():
            for f in sorted(agents_path.glob("*.md")):
                content = f.read_text()
                parts.append(f"### agents/{f.name}\n\n```\n{content}\n```\n")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _trim_to_budget(text: str, token_budget: int) -> str:
        """
        Trim assembled context to fit within the token budget.
        Cuts from the end (workspace files are last and largest),
        preserving the header and step outputs at the top.
        """
        char_budget = int(token_budget * CHARS_PER_TOKEN)
        if len(text) <= char_budget:
            return text
        trimmed = text[:char_budget]
        # Try to cut at a section boundary to avoid mid-file truncation
        last_section = trimmed.rfind("\n## ")
        if last_section > char_budget * 0.5:
            trimmed = trimmed[:last_section]
        trimmed += (
            "\n\n_[Context truncated to fit within token budget. "
            "Use `read_file` or `list_files` to access remaining workspace files.]_\n"
        )
        return trimmed

    @staticmethod
    def _is_ignored(path: Path) -> bool:
        ignored = {
            "__pycache__", ".pytest_cache", "node_modules",
            ".mypy_cache", "dist", "build", ".git",
        }
        return any(part in ignored for part in path.parts)

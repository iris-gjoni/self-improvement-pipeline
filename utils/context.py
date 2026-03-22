"""Build context messages for each pipeline step from accumulated run state."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.project_registry import ProjectRegistry


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

    def build_for_step(self, step: dict) -> str:
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
            parts.append(self._workspace_files_full(include_tests=True))

        elif step_id == "verification":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._section("TDD Red Results", "tdd_red"))
            parts.append(self._section("TDD Green Results", "tdd_green"))
            parts.append(self._workspace_files_full(include_tests=True))

        elif step_id == "integration":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._section("TDD Green Results", "tdd_green"))
            parts.append(self._section("Verification Results", "verification"))
            parts.append(self._workspace_files_full(include_tests=False))

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

        return "\n".join(p for p in parts if p.strip())

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

    def _workspace_files_full(self, include_tests: bool = True) -> str:
        if not self.workspace or not self.workspace.exists():
            return ""
        parts = ["## Workspace Files\n"]
        for p in sorted(self.workspace.rglob("*")):
            if not p.is_file() or self._is_ignored(p):
                continue
            rel = str(p.relative_to(self.workspace)).replace("\\", "/")
            if not include_tests and "test" in rel.lower():
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 6000:
                    content = content[:6000] + "\n... [truncated]"
                parts.append(f"### `{rel}`\n\n```\n{content}\n```\n")
            except Exception:
                parts.append(f"### `{rel}`\n\n_[could not read file]_\n")
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
        pipeline_path = self.workspace.parent.parent.parent / "pipeline.json"
        agents_path = self.workspace.parent.parent.parent / "agents"

        # Try BASE_DIR relative paths as fallback
        if not pipeline_path.exists():
            # Walk up from workspace to find pipeline.json
            search = self.workspace
            for _ in range(6):
                if (search / "pipeline.json").exists():
                    pipeline_path = search / "pipeline.json"
                    agents_path = search / "agents"
                    break
                search = search.parent

        parts = ["## Current Pipeline Configuration\n"]

        if pipeline_path.exists():
            content = pipeline_path.read_text()
            parts.append(f"### pipeline.json\n\n```json\n{content}\n```\n")

        if agents_path.exists():
            for f in sorted(agents_path.glob("*.md")):
                content = f.read_text()
                parts.append(f"### agents/{f.name}\n\n```\n{content}\n```\n")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ignored(path: Path) -> bool:
        ignored = {
            "__pycache__", ".pytest_cache", "node_modules",
            ".mypy_cache", "dist", "build", ".git",
        }
        return any(part in ignored for part in path.parts)

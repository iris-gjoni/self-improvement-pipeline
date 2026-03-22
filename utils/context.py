"""Build context messages for each pipeline step from accumulated run state."""

import json
from pathlib import Path
from typing import Any


class ContextBuilder:
    def __init__(
        self,
        context: dict,
        workspace: Path,
        feature_request: str,
        language: str,
    ):
        self.context = context
        self.workspace = workspace
        self.feature_request = feature_request
        self.language = language

    def build_for_step(self, step: dict) -> str:
        step_id = step["id"]
        parts = [f"## Feature Request\n\n{self.feature_request}\n"]
        parts.append(f"## Target Language\n\n{self.language}\n")

        # Include relevant prior step outputs
        if step_id == "requirements":
            pass  # First step, only has feature request

        elif step_id == "plan":
            parts.append(self._section("Requirements Specification", "requirements"))

        elif step_id == "tdd_red":
            parts.append(self._section("Requirements Specification", "requirements"))
            parts.append(self._section("Implementation Plan", "plan"))
            parts.append(self._workspace_structure())

        elif step_id == "tdd_green":
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

        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _section(self, title: str, step_id: str) -> str:
        data = self.context.get(step_id)
        if not data:
            return f"## {title}\n\n_Not available._\n"
        output = data.get("output", data)
        return f"## {title}\n\n```json\n{json.dumps(output, indent=2, default=str)}\n```\n"

    def _workspace_structure(self) -> str:
        if not self.workspace.exists():
            return ""
        files = []
        for p in sorted(self.workspace.rglob("*")):
            if p.is_file() and not self._is_ignored(p):
                rel = p.relative_to(self.workspace)
                files.append(f"  {str(rel).replace(chr(92), '/')}")
        if not files:
            return "## Workspace\n\n_Empty workspace._\n"
        listing = "\n".join(files)
        return f"## Workspace File Structure\n\n```\n{listing}\n```\n"

    def _workspace_files_full(self, include_tests: bool = True) -> str:
        if not self.workspace.exists():
            return ""
        parts = ["## Workspace Files\n"]
        for p in sorted(self.workspace.rglob("*")):
            if not p.is_file() or self._is_ignored(p):
                continue
            rel = str(p.relative_to(self.workspace)).replace("\\", "/")
            if not include_tests and ("test" in rel.lower()):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                # Truncate very large files
                if len(content) > 6000:
                    content = content[:6000] + "\n... [truncated]"
                parts.append(f"### `{rel}`\n\n```\n{content}\n```\n")
            except Exception:
                parts.append(f"### `{rel}`\n\n_[could not read file]_\n")
        return "\n".join(parts)

    def _pipeline_config(self) -> str:
        pipeline_path = self.workspace.parent.parent.parent / "pipeline.json"
        agents_path = self.workspace.parent.parent.parent / "agents"

        parts = ["## Current Pipeline Configuration\n"]

        if pipeline_path.exists():
            content = pipeline_path.read_text()
            parts.append(f"### pipeline.json\n\n```json\n{content}\n```\n")

        if agents_path.exists():
            for f in sorted(agents_path.glob("*.md")):
                content = f.read_text()
                parts.append(f"### agents/{f.name}\n\n```\n{content}\n```\n")

        return "\n".join(parts)

    def _is_ignored(self, path: Path) -> bool:
        ignored = {
            "__pycache__", ".pytest_cache", "node_modules",
            ".mypy_cache", "dist", "build", ".git",
        }
        return any(part in ignored for part in path.parts)

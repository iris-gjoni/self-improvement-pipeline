"""
Project registry — tracks known projects and manages their documentation folders.

The registry lives in projects.json and maps project names to metadata.
Each project gets a folder under docs/projects/{name}/ for living documentation.

New vs existing project detection:
  - If project_name is in the registry -> existing project
  - If project_dir matches a registered project_dir -> existing project (name resolved)
  - Otherwise -> new project (registered on first run)
"""

import json
import re
from datetime import datetime
from pathlib import Path


class ProjectRegistry:
    def __init__(self, registry_path: Path, docs_dir: Path):
        self.registry_path = registry_path
        self.docs_dir = docs_dir
        self._data = self._load()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def find(self, name: str) -> dict | None:
        """Return project entry by name, or None if not found."""
        return self._data["projects"].get(name)

    def find_by_dir(self, project_dir: Path) -> dict | None:
        """Return project entry whose project_dir matches, or None."""
        target = str(project_dir.resolve())
        for project in self._data["projects"].values():
            if project.get("project_dir") == target:
                return project
        return None

    def all(self) -> list[dict]:
        return list(self._data["projects"].values())

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        project_dir: Path | None,
        language: str,
        description: str = "",
    ) -> dict:
        """Register a new project and create its docs folder. Returns the entry."""
        doc_dir = self.get_doc_dir(name)
        doc_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "last_run_at": None,
            "project_dir": str(project_dir.resolve()) if project_dir else None,
            "language": language,
            "description": description,
            "runs": [],
        }
        self._data["projects"][name] = entry
        self._save()
        return entry

    def record_run(self, name: str, run_id: str) -> None:
        """Update last_run_at and append run_id to the project's run history."""
        if name in self._data["projects"]:
            self._data["projects"][name]["last_run_at"] = datetime.now().isoformat()
            runs = self._data["projects"][name].setdefault("runs", [])
            if run_id not in runs:
                runs.append(run_id)
            self._save()

    def update_description(self, name: str, description: str) -> None:
        if name in self._data["projects"]:
            self._data["projects"][name]["description"] = description
            self._save()

    # ------------------------------------------------------------------
    # Doc directory helpers
    # ------------------------------------------------------------------

    def get_doc_dir(self, name: str) -> Path:
        """Return the path to the project's documentation directory."""
        return self.docs_dir / "projects" / name

    def existing_docs(self, name: str) -> dict[str, str]:
        """Return {filename: content} for all .md files in the project's doc dir."""
        doc_dir = self.get_doc_dir(name)
        if not doc_dir.exists():
            return {}
        result = {}
        for f in sorted(doc_dir.glob("*.md")):
            try:
                result[f.name] = f.read_text(encoding="utf-8")
            except Exception:
                pass
        return result

    def doc_summary(self, name: str) -> str:
        """Return a Markdown summary of existing project docs for agent context."""
        docs = self.existing_docs(name)
        if not docs:
            return "_No existing documentation for this project._"
        parts = []
        for filename, content in docs.items():
            preview = content[:1500] + ("..." if len(content) > 1500 else "")
            parts.append(f"### `{filename}`\n\n{preview}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"projects": {}}

    def _save(self) -> None:
        self.registry_path.write_text(
            json.dumps(self._data, indent=2, default=str), encoding="utf-8"
        )


# ------------------------------------------------------------------
# Utilities used by runner.py
# ------------------------------------------------------------------


def slugify(text: str, max_len: int = 50) -> str:
    """Convert a free-form string into a URL-safe project name slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:max_len].rstrip("-")


def detect_language(project_dir: Path) -> str:
    """
    Auto-detect the primary language of an existing project directory.
    Returns 'python', 'typescript', 'javascript', or 'python' as default.
    """
    if not project_dir or not project_dir.exists():
        return "python"

    # Python indicators
    python_files = ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"]
    if any((project_dir / f).exists() for f in python_files):
        return "python"

    # TypeScript / JavaScript
    pkg_json = project_dir / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            all_deps = {
                **pkg.get("dependencies", {}),
                **pkg.get("devDependencies", {}),
            }
            if "typescript" in all_deps or (project_dir / "tsconfig.json").exists():
                return "typescript"
        except Exception:
            pass
        return "javascript"

    # Go
    if (project_dir / "go.mod").exists():
        return "go"

    # Fall back: look for source files
    py_files = list(project_dir.rglob("*.py"))
    ts_files = list(project_dir.rglob("*.ts"))
    js_files = list(project_dir.rglob("*.js"))

    counts = {"python": len(py_files), "typescript": len(ts_files), "javascript": len(js_files)}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] > 0 else "python"

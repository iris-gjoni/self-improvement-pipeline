"""
Workspace snapshot — detects new, modified, and deleted files.

Replaces the naive set-difference approach that only detected new files.
Uses file content hashes to detect modifications reliably.
"""

import hashlib
from pathlib import Path

IGNORED_DIRS = frozenset({
    "__pycache__", ".pytest_cache", "node_modules",
    ".mypy_cache", "dist", "build", ".git",
})


class WorkspaceSnapshot:
    """
    Captures a point-in-time snapshot of a workspace directory.
    Call .diff() after changes to get added/modified/deleted files.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._baseline: dict[str, str] = self._scan()

    def diff(self) -> dict:
        """
        Compare current workspace state against the baseline snapshot.

        Returns:
            {
                "added": [...],      # new files
                "modified": [...],   # files with changed content
                "deleted": [...],    # files removed since snapshot
                "all_changed": [...] # union of all three, sorted
            }
        """
        current = self._scan()
        baseline_keys = set(self._baseline)
        current_keys = set(current)

        added = sorted(current_keys - baseline_keys)
        deleted = sorted(baseline_keys - current_keys)
        modified = sorted(
            k for k in (baseline_keys & current_keys)
            if self._baseline[k] != current[k]
        )

        return {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "all_changed": sorted(set(added) | set(modified) | set(deleted)),
        }

    def _scan(self) -> dict[str, str]:
        """Return {relative_path: content_hash} for all non-ignored files."""
        if not self.workspace.exists():
            return {}
        result = {}
        for p in self.workspace.rglob("*"):
            if not p.is_file():
                continue
            if any(part in IGNORED_DIRS for part in p.parts):
                continue
            rel = str(p.relative_to(self.workspace)).replace("\\", "/")
            result[rel] = self._hash_file(p)
        return result

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Fast content hash using blake2b (faster than SHA-256, built-in)."""
        h = hashlib.blake2b(digest_size=16)
        try:
            h.update(path.read_bytes())
        except (OSError, PermissionError):
            return "unreadable"
        return h.hexdigest()


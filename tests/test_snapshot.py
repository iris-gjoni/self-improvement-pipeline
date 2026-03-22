"""Tests for workspace snapshot: detects new, modified, and deleted files."""

import time
import pytest
from pathlib import Path

from utils.snapshot import WorkspaceSnapshot


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestWorkspaceSnapshot:
    def test_detects_new_file(self, workspace):
        snap = WorkspaceSnapshot(workspace)
        (workspace / "new.py").write_text("hello")
        changes = snap.diff()
        assert "new.py" in changes["added"]

    def test_detects_modified_file(self, workspace):
        f = workspace / "existing.py"
        f.write_text("original")
        snap = WorkspaceSnapshot(workspace)
        f.write_text("modified")
        changes = snap.diff()
        assert "existing.py" in changes["modified"]

    def test_detects_deleted_file(self, workspace):
        f = workspace / "to_delete.py"
        f.write_text("goodbye")
        snap = WorkspaceSnapshot(workspace)
        f.unlink()
        changes = snap.diff()
        assert "to_delete.py" in changes["deleted"]

    def test_unchanged_file_not_reported(self, workspace):
        f = workspace / "stable.py"
        f.write_text("unchanged")
        snap = WorkspaceSnapshot(workspace)
        changes = snap.diff()
        assert "stable.py" not in changes["added"]
        assert "stable.py" not in changes["modified"]

    def test_all_changes_combined(self, workspace):
        """All change types in a single diff."""
        (workspace / "keep.py").write_text("original")
        (workspace / "remove.py").write_text("bye")
        snap = WorkspaceSnapshot(workspace)
        (workspace / "keep.py").write_text("changed")
        (workspace / "remove.py").unlink()
        (workspace / "brand_new.py").write_text("new")
        changes = snap.diff()
        assert changes["all_changed"] == sorted(["keep.py", "remove.py", "brand_new.py"])

    def test_ignores_pycache(self, workspace):
        snap = WorkspaceSnapshot(workspace)
        cache = workspace / "__pycache__"
        cache.mkdir()
        (cache / "mod.pyc").write_text("bytes")
        changes = snap.diff()
        assert len(changes["added"]) == 0

    def test_empty_workspace(self, workspace):
        snap = WorkspaceSnapshot(workspace)
        changes = snap.diff()
        assert changes["added"] == []
        assert changes["modified"] == []
        assert changes["deleted"] == []

    def test_subdirectory_files(self, workspace):
        snap = WorkspaceSnapshot(workspace)
        sub = workspace / "src" / "deep"
        sub.mkdir(parents=True)
        (sub / "mod.py").write_text("code")
        changes = snap.diff()
        assert "src/deep/mod.py" in changes["added"]


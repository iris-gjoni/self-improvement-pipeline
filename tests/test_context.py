"""Tests for context builder: step context assembly and token budgeting."""

import json
import pytest
from pathlib import Path

from utils.context import ContextBuilder


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "__init__.py").write_text("")
    (ws / "src" / "app.py").write_text("def main(): pass")
    (ws / "tests").mkdir()
    (ws / "tests" / "test_app.py").write_text("def test_main(): assert True")
    return ws


def make_builder(workspace, context=None, **kwargs):
    defaults = dict(
        context=context or {},
        workspace=workspace,
        feature_request="Build a todo app",
        language="python",
        project_name="test-project",
        is_new_project=True,
    )
    defaults.update(kwargs)
    return ContextBuilder(**defaults)


class TestContextBuilding:
    def test_requirements_step_includes_header(self, workspace):
        builder = make_builder(workspace)
        step = {"id": "requirements"}
        ctx = builder.build_for_step(step)
        assert "Build a todo app" in ctx
        assert "test-project" in ctx
        assert "python" in ctx

    def test_plan_step_includes_requirements(self, workspace):
        context = {"requirements": {"status": "success", "output": {"title": "Todo App"}}}
        builder = make_builder(workspace, context=context)
        step = {"id": "plan"}
        ctx = builder.build_for_step(step)
        assert "Todo App" in ctx
        assert "Requirements Specification" in ctx

    def test_tdd_green_includes_workspace_files(self, workspace):
        context = {
            "requirements": {"output": {"title": "x"}},
            "plan": {"output": {"architecture": "y"}},
        }
        builder = make_builder(workspace, context=context)
        step = {"id": "tdd_green"}
        ctx = builder.build_for_step(step)
        assert "app.py" in ctx
        assert "def main" in ctx

    def test_missing_step_output_shows_not_available(self, workspace):
        builder = make_builder(workspace)
        step = {"id": "plan"}
        ctx = builder.build_for_step(step)
        assert "_Not available._" in ctx

    def test_existing_project_context(self, workspace):
        builder = make_builder(workspace, is_new_project=False)
        step = {"id": "requirements"}
        ctx = builder.build_for_step(step)
        assert "Existing Project" in ctx


class TestTokenBudget:
    def test_large_files_are_truncated(self, workspace):
        """Files larger than the per-file limit should be truncated."""
        large_file = workspace / "src" / "big.py"
        large_file.write_text("x = 1\n" * 5000)  # ~30KB
        builder = make_builder(workspace)
        step = {"id": "tdd_green"}
        ctx = builder.build_for_step(step)
        # The file should appear but be truncated
        assert "big.py" in ctx
        assert "truncated" in ctx

    def test_context_respects_max_tokens(self, workspace):
        """When a token budget is set, the context should be bounded."""
        # Create a bunch of files
        for i in range(50):
            (workspace / "src" / f"module_{i}.py").write_text(f"# module {i}\n" * 200)
        builder = make_builder(workspace)
        step = {"id": "tdd_green"}
        ctx = builder.build_for_step(step, max_context_tokens=8000)
        # Rough estimate: 8000 tokens ~ 32000 chars. Context should be bounded.
        assert len(ctx) < 50000  # generous upper bound
        assert "[context truncated" in ctx.lower() or len(ctx) < 40000


class TestIgnoredPaths:
    def test_pycache_ignored(self, workspace):
        cache = workspace / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-313.pyc").write_text("bytecode")
        builder = make_builder(workspace)
        step = {"id": "tdd_red"}
        ctx = builder.build_for_step(step)
        assert "__pycache__" not in ctx

    def test_node_modules_ignored(self, workspace):
        nm = workspace / "node_modules"
        nm.mkdir()
        (nm / "pkg").mkdir()
        (nm / "pkg" / "index.js").write_text("module.exports = {}")
        builder = make_builder(workspace)
        step = {"id": "tdd_red"}
        ctx = builder.build_for_step(step)
        assert "node_modules" not in ctx


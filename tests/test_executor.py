"""Tests for workspace executor: file operations, test running, security."""

import pytest
from pathlib import Path

from utils.executor import WorkspaceExecutor


LANGUAGES_CONFIG = {
    "python": {
        "file_extension": ".py",
        "test_framework": "pytest",
        "test_command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
        "install_command": ["pip", "install", "-r", "requirements.txt", "-q"],
    },
}


@pytest.fixture
def executor(tmp_path):
    return WorkspaceExecutor(tmp_path, "python", LANGUAGES_CONFIG)


class TestFileOperations:
    def test_write_and_read(self, executor, tmp_path):
        executor.write_workspace_file("src/hello.py", "print('hello')")
        content = executor.read_workspace_file("src/hello.py")
        assert content == "print('hello')"
        assert (tmp_path / "src" / "hello.py").exists()

    def test_write_creates_subdirs(self, executor, tmp_path):
        executor.write_workspace_file("a/b/c/d.txt", "deep")
        assert (tmp_path / "a" / "b" / "c" / "d.txt").read_text() == "deep"

    def test_read_nonexistent_raises(self, executor):
        with pytest.raises(FileNotFoundError):
            executor.read_workspace_file("nope.py")

    def test_path_traversal_blocked_on_write(self, executor):
        with pytest.raises(ValueError, match="outside"):
            executor.write_workspace_file("../../etc/passwd", "hacked")

    def test_path_traversal_blocked_on_read(self, executor):
        with pytest.raises(ValueError, match="outside"):
            executor.read_workspace_file("../../etc/passwd")

    def test_list_files(self, executor, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "c.pyc").write_text("")
        files = executor.list_workspace_files()
        paths = [f["path"] for f in files]
        assert "a.py" in paths
        assert "sub/b.py" in paths
        assert not any("__pycache__" in p for p in paths)


class TestTestParsing:
    def test_parse_pytest_success(self, executor):
        raw = "tests/test_a.py::test_one PASSED\ntests/test_a.py::test_two PASSED\n\n2 passed in 0.5s"
        result = executor._parse_pytest(0, raw)
        assert result["passed"] is True
        assert result["passed_count"] == 2
        assert result["failed_count"] == 0

    def test_parse_pytest_failure(self, executor):
        raw = "tests/test_a.py::test_one PASSED\ntests/test_a.py::test_two FAILED\n\n1 passed, 1 failed in 0.5s"
        result = executor._parse_pytest(1, raw)
        assert result["passed"] is False
        assert result["failed_count"] == 1

    def test_parse_pytest_no_tests(self, executor):
        result = executor._parse_pytest(5, "no tests ran")
        assert result["passed"] is False
        assert result["total"] == 0


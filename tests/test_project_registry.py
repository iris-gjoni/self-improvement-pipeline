"""Tests for project registry: registration, lookup, and doc management."""

import json
import pytest
from pathlib import Path

from utils.project_registry import ProjectRegistry, slugify, detect_language


@pytest.fixture
def registry(tmp_path):
    """Fresh registry backed by a temp directory."""
    return ProjectRegistry(
        registry_path=tmp_path / "projects.json",
        docs_dir=tmp_path / "docs",
    )


class TestProjectRegistration:
    def test_register_and_find(self, registry):
        registry.register("my-app", project_dir=None, language="python", description="A test app")
        found = registry.find("my-app")
        assert found is not None
        assert found["name"] == "my-app"
        assert found["language"] == "python"

    def test_find_returns_none_for_unknown(self, registry):
        assert registry.find("nonexistent") is None

    def test_find_by_dir(self, registry, tmp_path):
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        registry.register("dir-app", project_dir=project_dir, language="typescript")
        found = registry.find_by_dir(project_dir)
        assert found is not None
        assert found["name"] == "dir-app"

    def test_record_run_updates_history(self, registry):
        registry.register("app", project_dir=None, language="python")
        registry.record_run("app", "run-001")
        registry.record_run("app", "run-002")
        entry = registry.find("app")
        assert entry["runs"] == ["run-001", "run-002"]
        assert entry["last_run_at"] is not None

    def test_record_run_deduplicates(self, registry):
        registry.register("app", project_dir=None, language="python")
        registry.record_run("app", "run-001")
        registry.record_run("app", "run-001")
        assert registry.find("app")["runs"] == ["run-001"]

    def test_doc_dir_created_on_register(self, registry):
        registry.register("doc-app", project_dir=None, language="python")
        doc_dir = registry.get_doc_dir("doc-app")
        assert doc_dir.exists()

    def test_existing_docs_returns_md_files(self, registry):
        registry.register("app", project_dir=None, language="python")
        doc_dir = registry.get_doc_dir("app")
        (doc_dir / "README.md").write_text("# Hello")
        (doc_dir / "notes.txt").write_text("ignored")
        docs = registry.existing_docs("app")
        assert "README.md" in docs
        assert "notes.txt" not in docs

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "projects.json"
        docs = tmp_path / "docs"
        r1 = ProjectRegistry(path, docs)
        r1.register("persist-app", project_dir=None, language="python")
        r2 = ProjectRegistry(path, docs)
        assert r2.find("persist-app") is not None


class TestSlugify:
    def test_basic(self):
        assert slugify("Build a REST API") == "build-a-rest-api"

    def test_strips_special_chars(self):
        assert slugify("Hello, World!") == "hello-world"

    def test_truncates(self):
        result = slugify("a" * 100, max_len=10)
        assert len(result) <= 10


class TestDetectLanguage:
    def test_python_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("")
        assert detect_language(tmp_path) == "python"

    def test_typescript_from_tsconfig(self, tmp_path):
        (tmp_path / "package.json").write_text('{"devDependencies": {"typescript": "^5"}}')
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_language(tmp_path) == "typescript"

    def test_defaults_to_python(self, tmp_path):
        assert detect_language(tmp_path) == "python"


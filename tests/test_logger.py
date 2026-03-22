"""Tests for step logger: run metadata and event logging."""

import json
import pytest
from pathlib import Path

from utils.logger import StepLogger


@pytest.fixture
def logger(tmp_path):
    return StepLogger(tmp_path / "run-001")


class TestStepLogger:
    def test_save_and_load_run_meta(self, logger):
        meta = {"id": "run-001", "status": "running", "feature": "test"}
        logger.save_run_meta(meta)
        loaded = logger.load_run_meta()
        assert loaded["id"] == "run-001"
        assert loaded["status"] == "running"

    def test_save_and_load_step(self, logger):
        data = {"status": "success", "output": {"title": "Test"}}
        logger.save_step("requirements", data)
        loaded = logger.load_step("requirements")
        assert loaded["status"] == "success"
        assert loaded["output"]["title"] == "Test"

    def test_load_missing_step_returns_none(self, logger):
        assert logger.load_step("nonexistent") is None

    def test_load_missing_meta_returns_none(self, tmp_path):
        logger = StepLogger(tmp_path / "missing-run")
        assert logger.load_run_meta() is None

    def test_log_event_appends(self, logger):
        logger.log_event("step_start", {"step_id": "plan"})
        logger.log_event("step_complete", {"step_id": "plan", "status": "success"})
        events_path = logger.run_dir / "events.jsonl"
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "step_start"
        assert json.loads(lines[1])["event"] == "step_complete"

    def test_creates_run_dir(self, tmp_path):
        run_dir = tmp_path / "new" / "nested" / "run"
        logger = StepLogger(run_dir)
        assert run_dir.exists()


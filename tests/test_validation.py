"""Tests for step output validation."""

import pytest

from utils.validation import validate_step_output, StepOutputError


class TestRequirementsValidation:
    def test_valid_requirements(self):
        output = {
            "title": "Todo App",
            "summary": "A todo application",
            "acceptance_criteria": [
                {"id": "AC-001", "description": "Given X, when Y, then Z"}
            ],
        }
        # Should not raise
        validate_step_output("requirements", {"output": output})

    def test_missing_acceptance_criteria(self):
        output = {"title": "Todo", "summary": "A todo app"}
        with pytest.raises(StepOutputError, match="acceptance_criteria"):
            validate_step_output("requirements", {"output": output})

    def test_empty_acceptance_criteria(self):
        output = {"title": "Todo", "summary": "A todo app", "acceptance_criteria": []}
        with pytest.raises(StepOutputError, match="acceptance_criteria"):
            validate_step_output("requirements", {"output": output})

    def test_nested_output_key(self):
        """Handle the double-nested {output: {output: {...}}} pattern."""
        inner = {
            "title": "Todo",
            "summary": "test",
            "acceptance_criteria": [{"id": "AC-001", "description": "test"}],
        }
        validate_step_output("requirements", {"output": {"output": inner}})


class TestPlanValidation:
    def test_valid_plan(self):
        output = {
            "architecture_overview": "A simple app",
            "file_structure": [{"path": "src/app.py"}],
            "components": [{"name": "App"}],
        }
        validate_step_output("plan", {"output": output})

    def test_missing_file_structure(self):
        output = {"architecture_overview": "A simple app"}
        with pytest.raises(StepOutputError, match="file_structure"):
            validate_step_output("plan", {"output": output})


class TestTddOutputValidation:
    def test_tdd_red_with_files(self):
        validate_step_output("tdd_red", {"files_written": ["tests/test_app.py"]})

    def test_tdd_red_no_files(self):
        with pytest.raises(StepOutputError, match="files"):
            validate_step_output("tdd_red", {"files_written": []})

    def test_tdd_green_with_files(self):
        validate_step_output("tdd_green", {"files_written": ["src/app.py"]})


class TestVerificationValidation:
    def test_valid_verification(self):
        output = {
            "overall_status": "pass",
            "criteria_results": [{"id": "AC-001", "status": "pass"}],
        }
        validate_step_output("verification", {"output": output})

    def test_missing_criteria_results(self):
        output = {"overall_status": "pass"}
        with pytest.raises(StepOutputError, match="criteria_results"):
            validate_step_output("verification", {"output": output})


class TestParseErrorDetection:
    def test_parse_error_key_raises(self):
        with pytest.raises(StepOutputError, match="parse"):
            validate_step_output("requirements", {
                "summary": "raw text",
                "_parse_error": "Could not extract JSON",
            })

    def test_interactive_missing_output_raises(self):
        with pytest.raises(StepOutputError, match="missing"):
            validate_step_output("requirements", {
                "output": "",
                "_interactive_missing_output": True,
            })


class TestUnknownStepPassesThrough:
    def test_unknown_step_no_validation(self):
        """Steps without specific validators should pass through."""
        validate_step_output("some_future_step", {"anything": "goes"})


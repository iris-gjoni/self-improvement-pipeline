"""Tests for postmortem output unwrapping logic.

The postmortem step's result can arrive at different nesting levels
depending on which runner is used. This test verifies the unwrapping
works for all known patterns.
"""



def unwrap_postmortem_result(result: dict) -> dict:
    """
    Extracted unwrapping logic from runner.py _run_postmortem_step.
    Returns the innermost dict containing postmortem keys.
    """
    inner = result
    for _ in range(3):
        if isinstance(inner, dict) and "output" in inner and isinstance(inner["output"], dict):
            candidate = inner["output"]
            if any(k in candidate for k in ("analysis", "proposals", "run_summary", "output")):
                inner = candidate
            else:
                break
        else:
            break
    return inner


class TestPostmortemUnwrapping:
    """Test that proposals are correctly extracted regardless of nesting."""

    PROPOSALS = [
        {"id": "P-001", "title": "Fix X", "type": "update_agent",
         "rationale": "...", "priority": "high", "operations": []},
        {"id": "P-002", "title": "Fix Y", "type": "update_pipeline",
         "rationale": "...", "priority": "medium", "operations": []},
    ]

    def test_flat_result_from_api_mode(self):
        """API mode: run_postmortem returns tool input directly."""
        result = {
            "analysis": "Everything was fine",
            "run_summary": {"overall_quality": "good", "key_issues": [], "key_successes": []},
            "proposals": self.PROPOSALS,
        }
        inner = unwrap_postmortem_result(result)
        assert len(inner["proposals"]) == 2

    def test_single_nested_output(self):
        """Interactive/CC mode: result wrapped in one layer of 'output'."""
        result = {
            "output": {
                "analysis": "Everything was fine",
                "run_summary": {"overall_quality": "good", "key_issues": [], "key_successes": []},
                "proposals": self.PROPOSALS,
            }
        }
        inner = unwrap_postmortem_result(result)
        assert len(inner["proposals"]) == 2
        assert inner["analysis"] == "Everything was fine"

    def test_double_nested_output(self):
        """The actual bug: double-nested output from interactive mode."""
        result = {
            "output": {
                "output": {
                    "analysis": {"summary": "detailed analysis..."},
                    "run_summary": {"overall_quality": "fair", "key_issues": ["x"], "key_successes": []},
                    "proposals": self.PROPOSALS,
                }
            }
        }
        inner = unwrap_postmortem_result(result)
        assert "proposals" in inner
        assert len(inner["proposals"]) == 2

    def test_no_proposals_key_returns_empty(self):
        """If the model didn't produce proposals at all."""
        result = {
            "analysis": "Something happened",
            "run_summary": {"overall_quality": "poor", "key_issues": [], "key_successes": []},
        }
        inner = unwrap_postmortem_result(result)
        assert inner.get("proposals", []) == []

    def test_unrelated_output_key_not_unwrapped(self):
        """If 'output' contains unrelated data, don't unwrap it."""
        result = {
            "analysis": "top-level analysis",
            "proposals": self.PROPOSALS,
            "output": {"some_other_key": "value"},
        }
        inner = unwrap_postmortem_result(result)
        assert len(inner["proposals"]) == 2
        assert inner["analysis"] == "top-level analysis"

    def test_analysis_as_dict_preserved(self):
        """Analysis can be a dict (detailed breakdown) — should be preserved."""
        result = {
            "analysis": {"summary": "...", "step_analysis": {"req": "good"}},
            "run_summary": {"overall_quality": "good", "key_issues": [], "key_successes": []},
            "proposals": self.PROPOSALS,
        }
        inner = unwrap_postmortem_result(result)
        assert isinstance(inner["analysis"], dict)
        assert len(inner["proposals"]) == 2

    def test_real_bug_reproduction(self):
        """Reproduce the exact structure from the 2026-03-22T175049 run."""
        result = {
            "output": {
                "analysis": {
                    "summary": "The snake-game pipeline run ultimately succeeded...",
                    "step_analysis": {"requirements": {"quality": "good"}},
                },
                "proposals": [
                    {"id": f"P-{i:03d}", "title": f"Fix {i}", "type": "update_agent",
                     "rationale": "...", "priority": "high", "operations": []}
                    for i in range(1, 7)
                ],
            }
        }
        inner = unwrap_postmortem_result(result)
        assert len(inner["proposals"]) == 6

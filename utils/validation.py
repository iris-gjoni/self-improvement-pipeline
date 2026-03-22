"""
Step output validation.

Validates that each pipeline step produced structurally correct output
before it is passed downstream. Catches malformed JSON, missing required
fields, and parse errors early — rather than letting garbage propagate
through the entire pipeline.
"""


class StepOutputError(Exception):
    """Raised when a step's output is structurally invalid."""

    def __init__(self, step_id: str, message: str):
        self.step_id = step_id
        super().__init__(f"Step '{step_id}' output invalid: {message}")


def validate_step_output(step_id: str, result: dict) -> None:
    """
    Validate a step's result dict. Raises StepOutputError if the output
    is structurally broken (missing required keys, parse errors, etc.).

    Does NOT validate semantic correctness — just structural sanity.
    """
    # Check for parse errors from Claude Code / interactive runners
    if result.get("_parse_error"):
        raise StepOutputError(step_id, f"Output could not be parsed: {result['_parse_error']}")
    if result.get("_interactive_missing_output"):
        raise StepOutputError(step_id, "Interactive session did not produce output (missing _step_output.json)")

    validator = _VALIDATORS.get(step_id)
    if validator:
        validator(step_id, result)


# ---------------------------------------------------------------------------
# Per-step validators
# ---------------------------------------------------------------------------

def _unwrap_output(result: dict) -> dict:
    """
    Unwrap the output from a result dict, handling the double-nested
    {output: {output: {...}}} pattern that the API agent sometimes produces.
    """
    output = result.get("output", result)
    if isinstance(output, dict) and "output" in output and isinstance(output["output"], dict):
        output = output["output"]
    return output


def _validate_requirements(step_id: str, result: dict) -> None:
    output = _unwrap_output(result)
    if not isinstance(output, dict):
        raise StepOutputError(step_id, "Output is not a dict")
    ac = output.get("acceptance_criteria")
    if not ac or not isinstance(ac, list) or len(ac) == 0:
        raise StepOutputError(
            step_id,
            "Missing or empty 'acceptance_criteria'. "
            "The requirements agent must produce at least one acceptance criterion."
        )


def _validate_plan(step_id: str, result: dict) -> None:
    output = _unwrap_output(result)
    if not isinstance(output, dict):
        raise StepOutputError(step_id, "Output is not a dict")
    if not output.get("file_structure"):
        raise StepOutputError(
            step_id,
            "Missing 'file_structure'. The plan must define the files to create."
        )


def _validate_tdd_red(step_id: str, result: dict) -> None:
    files = result.get("files_written") or []
    output = result.get("output")
    if isinstance(output, dict):
        files = files or output.get("files_written") or []
    if not files:
        raise StepOutputError(
            step_id,
            "No test files were written. TDD Red must produce at least one test file."
        )


def _validate_tdd_green(step_id: str, result: dict) -> None:
    # TDD green is validated by the test runner, but check basic structure
    files = result.get("files_written") or []
    output = result.get("output")
    if isinstance(output, dict):
        files = files or output.get("files_written") or []
    if not files:
        raise StepOutputError(
            step_id,
            "No implementation files were written. TDD Green must produce source files."
        )


def _validate_verification(step_id: str, result: dict) -> None:
    output = _unwrap_output(result)
    if not isinstance(output, dict):
        raise StepOutputError(step_id, "Output is not a dict")
    if not output.get("criteria_results"):
        raise StepOutputError(
            step_id,
            "Missing 'criteria_results'. Verification must assess each acceptance criterion."
        )


_VALIDATORS = {
    "requirements": _validate_requirements,
    "plan": _validate_plan,
    "tdd_red": _validate_tdd_red,
    "tdd_green": _validate_tdd_green,
    "verification": _validate_verification,
}



"""Agent runner: handles the tool-use loop for all pipeline agents."""

import json
import time
from pathlib import Path
from typing import Any

import anthropic
from rich.console import Console

console = Console()

# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

STRUCTURED_TOOLS = [
    {
        "name": "complete",
        "description": (
            "Submit your final structured output. Call this ONLY when your analysis is complete. "
            "The `output` field must match the schema described in your instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "output": {
                    "type": "object",
                    "description": "Your complete structured output as described in your instructions.",
                }
            },
            "required": ["output"],
        },
    }
]

FILE_TOOLS = [
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the workspace. Use relative paths (e.g. 'src/foo.py').",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within workspace"},
                "content": {"type": "string", "description": "Complete file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read an existing file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within workspace"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List all files in the workspace (or a subdirectory).",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to list (default: '.')",
                    "default": ".",
                },
            },
        },
    },
    {
        "name": "complete",
        "description": (
            "Signal that you have finished writing all files. "
            "Include a summary of what you wrote and why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of what was written"},
                "files_written": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths written",
                },
            },
            "required": ["summary", "files_written"],
        },
    },
]

FILE_TOOLS_WITH_TESTS = FILE_TOOLS + [
    {
        "name": "run_tests",
        "description": (
            "Run the test suite in the workspace and see results. "
            "Use this to check your progress after writing implementation files. "
            "Optionally specify a test_path to run a subset of tests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Optional: path to test file or directory",
                },
            },
        },
    },
]

POSTMORTEM_TOOLS = [
    {
        "name": "complete",
        "description": "Submit the complete post-mortem analysis and proposals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis": {
                    "type": "string",
                    "description": "Narrative analysis of the pipeline run",
                },
                "run_summary": {
                    "type": "object",
                    "properties": {
                        "overall_quality": {
                            "type": "string",
                            "enum": ["excellent", "good", "fair", "poor"],
                        },
                        "key_issues": {"type": "array", "items": {"type": "string"}},
                        "key_successes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["overall_quality", "key_issues", "key_successes"],
                },
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "update_agent",
                                    "update_pipeline",
                                    "add_step",
                                    "remove_step",
                                    "create_skill",
                                    "update_docs",
                                    "other",
                                ],
                            },
                            "title": {"type": "string"},
                            "rationale": {"type": "string"},
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "operations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {
                                            "type": "string",
                                            "enum": ["write", "delete", "append"],
                                        },
                                        "path": {"type": "string"},
                                        "content": {"type": "string"},
                                    },
                                    "required": ["action", "path"],
                                },
                            },
                        },
                        "required": ["id", "type", "title", "rationale", "priority", "operations"],
                    },
                },
            },
            "required": ["analysis", "run_summary", "proposals"],
        },
    }
]


# ------------------------------------------------------------------
# AgentRunner
# ------------------------------------------------------------------


class AgentRunner:
    def __init__(self, client: anthropic.Anthropic, agents_dir: Path):
        self.client = client
        self.agents_dir = agents_dir

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def run_structured(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        schema: dict | None,
        step_id: str,
        max_tokens: int = 8192,
    ) -> dict:
        """Run an agent that produces structured JSON output (no file writing)."""
        messages = [{"role": "user", "content": user_message}]
        result, _ = self._tool_loop(
            system=system_prompt,
            messages=messages,
            tools=STRUCTURED_TOOLS,
            model=model,
            max_tokens=max_tokens,
        )
        return result.get("output", result)

    def run_with_files(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        workspace: Path,
        executor,
        can_run_tests: bool = False,
        max_tokens: int = 8192,
    ) -> dict:
        """Run an agent that writes files to the workspace."""
        result, _ = self.run_with_files_stateful(
            system_prompt=system_prompt,
            user_message=user_message,
            retry_message=None,
            messages=None,
            model=model,
            workspace=workspace,
            executor=executor,
            can_run_tests=can_run_tests,
            max_tokens=max_tokens,
        )
        return result

    def run_with_files_stateful(
        self,
        system_prompt: str,
        user_message: str | None,
        retry_message: str | None,
        messages: list | None,
        model: str,
        workspace: Path,
        executor,
        can_run_tests: bool = False,
        max_tokens: int = 8192,
    ) -> tuple[dict, list]:
        """Run an agent with file tools, returning messages for stateful retries."""
        tools = FILE_TOOLS_WITH_TESTS if can_run_tests else FILE_TOOLS

        if messages is None:
            messages = [{"role": "user", "content": user_message}]
        elif retry_message:
            messages.append({"role": "user", "content": retry_message})

        result, messages = self._tool_loop(
            system=system_prompt,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            workspace=workspace,
            executor=executor,
        )
        return result, messages

    def run_postmortem(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 16000,
    ) -> dict:
        """Run the post-mortem agent (opus) with extended output."""
        messages = [{"role": "user", "content": user_message}]
        result, _ = self._tool_loop(
            system=system_prompt,
            messages=messages,
            tools=POSTMORTEM_TOOLS,
            model=model,
            max_tokens=max_tokens,
        )
        return result

    # ------------------------------------------------------------------
    # Core tool loop
    # ------------------------------------------------------------------

    def _tool_loop(
        self,
        system: str,
        messages: list,
        tools: list,
        model: str,
        max_tokens: int = 8192,
        workspace: Path | None = None,
        executor=None,
        max_iterations: int = 50,
    ) -> tuple[dict, list]:
        files_written: list[str] = []

        for iteration in range(max_iterations):
            response = self._call_api(system, messages, tools, model, max_tokens)

            # Collect tool calls and check for complete
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            complete_result = None
            tool_results = []

            for block in tool_uses:
                tool_result = self._execute_tool(
                    block.name, block.input, workspace, executor, files_written
                )
                if block.name == "complete":
                    complete_result = block.input
                    # Still need to send tool result back
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": (
                            json.dumps(tool_result)
                            if not isinstance(tool_result, str)
                            else tool_result
                        ),
                    }
                )

            # Always append the assistant turn + tool results
            messages.append({"role": "assistant", "content": response.content})
            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if complete_result is not None:
                # Attach accumulated files_written if this was a file-writing agent
                if "files_written" not in complete_result:
                    complete_result["files_written"] = files_written
                return complete_result, messages

            # If no tool use and end_turn, extract text as fallback
            if response.stop_reason == "end_turn" and not tool_uses:
                text = " ".join(
                    b.text for b in response.content if hasattr(b, "text")
                )
                return {"summary": text, "files_written": files_written}, messages

        raise RuntimeError(
            f"Agent exceeded maximum iterations ({max_iterations}) without calling complete."
        )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(
        self,
        name: str,
        inputs: dict,
        workspace: Path | None,
        executor,
        files_written: list[str],
    ) -> Any:
        if name == "complete":
            return {"status": "acknowledged"}

        if name == "write_file" and workspace:
            path = inputs["path"]
            content = inputs["content"]
            try:
                executor.write_workspace_file(path, content)
                if path not in files_written:
                    files_written.append(path)
                console.print(f"    [dim]  wrote {path}[/dim]")
                return {"success": True, "path": path}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if name == "read_file" and workspace:
            path = inputs["path"]
            try:
                content = executor.read_workspace_file(path)
                return {"success": True, "content": content}
            except FileNotFoundError:
                return {"success": False, "error": f"File not found: {path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if name == "list_files" and workspace:
            directory = inputs.get("directory", ".")
            files = executor.list_workspace_files(directory)
            return {"files": files}

        if name == "run_tests" and executor:
            test_path = inputs.get("test_path")
            console.print(f"    [dim]  running tests{' (' + test_path + ')' if test_path else ''}...[/dim]")
            result = executor.run_tests(test_path)
            console.print(
                f"    [dim]  → {result['passed_count']} passed, "
                f"{result['failed_count']} failed, "
                f"{result['error_count']} errors[/dim]"
            )
            return {
                "passed": result["passed"],
                "total": result["total"],
                "passed_count": result["passed_count"],
                "failed_count": result["failed_count"],
                "error_count": result["error_count"],
                "output": result["formatted_output"],
            }

        return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # API call with retry
    # ------------------------------------------------------------------

    def _call_api(
        self,
        system: str,
        messages: list,
        tools: list,
        model: str,
        max_tokens: int,
        retries: int = 3,
    ) -> anthropic.types.Message:
        for attempt in range(retries):
            try:
                return self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                )
            except anthropic.RateLimitError:
                if attempt < retries - 1:
                    wait = 60 * (attempt + 1)
                    console.print(f"    [yellow]Rate limited. Waiting {wait}s...[/yellow]")
                    time.sleep(wait)
                else:
                    raise
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < retries - 1:
                    wait = 30 * (attempt + 1)
                    console.print(f"    [yellow]API overloaded. Waiting {wait}s...[/yellow]")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("API call failed after all retries")

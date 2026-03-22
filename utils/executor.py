"""Workspace code execution: test running, type checking, dependency installation."""

import re
import subprocess
from pathlib import Path
from typing import Any


class WorkspaceExecutor:
    def __init__(self, workspace: Path, language: str, languages_config: dict):
        self.workspace = workspace
        self.language = language
        self.config = languages_config.get(language, {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install_dependencies(self) -> dict:
        cmd = self.config.get("install_command")
        if not cmd:
            return {"success": True, "output": ""}

        # Only run if dep file exists
        dep_file = self._dep_file()
        if dep_file and not (self.workspace / dep_file).exists():
            return {"success": True, "output": "No dependency file found, skipping install."}

        result = self._run(cmd, timeout=180)
        return {
            "success": result.returncode == 0,
            "output": (result.stdout + result.stderr)[-2000:],
            "returncode": result.returncode,
        }

    def run_tests(self, test_path: str | None = None) -> dict:
        cmd = list(self.config.get("test_command", []))
        if not cmd:
            return self._empty_test_result("No test command configured.")

        if test_path:
            cmd.append(test_path)

        result = self._run(cmd, timeout=120)
        raw = result.stdout + result.stderr
        return self._parse_test_output(result.returncode, raw)

    def run_integration_tests(self) -> dict:
        cmd = self.config.get("integration_test_command")
        if not cmd:
            return self._empty_test_result("No integration test command configured.")

        result = self._run(cmd, timeout=180)
        raw = result.stdout + result.stderr
        return self._parse_test_output(result.returncode, raw)

    def run_type_check(self) -> dict:
        cmd = self.config.get("type_check_command")
        if not cmd:
            return {"errors": [], "warnings": [], "raw_output": "", "passed": True}

        result = self._run(cmd, timeout=60)
        raw = result.stdout + result.stderr
        errors = self._extract_type_errors(raw)
        return {
            "passed": result.returncode == 0,
            "errors": errors,
            "raw_output": raw[-3000:],
            "returncode": result.returncode,
        }

    def list_workspace_files(self, directory: str = ".") -> list[dict]:
        target = (self.workspace / directory).resolve()
        if not target.is_dir():
            return []

        files = []
        for path in sorted(target.rglob("*")):
            if path.is_file() and not self._is_ignored(path):
                rel = path.relative_to(self.workspace)
                files.append({
                    "path": str(rel).replace("\\", "/"),
                    "size": path.stat().st_size,
                })
        return files

    def read_workspace_file(self, path: str) -> str:
        target = (self.workspace / path).resolve()
        # Security: must be within workspace
        try:
            target.relative_to(self.workspace.resolve())
        except ValueError:
            raise ValueError(f"Path '{path}' is outside the workspace.")
        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_workspace_file(self, path: str, content: str) -> None:
        target = (self.workspace / path).resolve()
        try:
            target.relative_to(self.workspace.resolve())
        except ValueError:
            raise ValueError(f"Path '{path}' is outside the workspace.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, cmd: list, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _dep_file(self) -> str | None:
        mapping = {
            "python": "requirements.txt",
            "typescript": "package.json",
            "javascript": "package.json",
        }
        return mapping.get(self.language)

    def _is_ignored(self, path: Path) -> bool:
        ignored_dirs = {
            "__pycache__", ".pytest_cache", "node_modules",
            ".mypy_cache", "dist", "build", ".git",
        }
        return any(part in ignored_dirs for part in path.parts)

    def _empty_test_result(self, reason: str) -> dict:
        return {
            "passed": False,
            "total": 0,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 0,
            "raw_output": reason,
            "formatted_output": reason,
            "returncode": -1,
        }

    def _parse_test_output(self, returncode: int, raw: str) -> dict:
        lang = self.language
        if lang == "python":
            return self._parse_pytest(returncode, raw)
        elif lang in ("typescript", "javascript"):
            return self._parse_jest(returncode, raw)
        else:
            return {
                "passed": returncode == 0,
                "total": 0,
                "passed_count": 0,
                "failed_count": 0,
                "error_count": 0,
                "raw_output": raw,
                "formatted_output": raw[-4000:],
                "returncode": returncode,
            }

    def _parse_pytest(self, returncode: int, raw: str) -> dict:
        passed = len(re.findall(r"\bPASSED\b", raw))
        failed = len(re.findall(r"\bFAILED\b", raw))
        errors = len(re.findall(r"\bERROR\b", raw))
        total = passed + failed + errors

        # Also try summary line: "5 passed, 2 failed"
        if total == 0:
            m = re.search(r"(\d+) passed", raw)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", raw)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) error", raw)
            if m:
                errors = int(m.group(1))
            total = passed + failed + errors

        # Trim output to last 4000 chars (most relevant)
        formatted = raw[-4000:] if len(raw) > 4000 else raw

        return {
            "passed": returncode == 0 and total > 0 and failed == 0 and errors == 0,
            "total": total,
            "passed_count": passed,
            "failed_count": failed,
            "error_count": errors,
            "raw_output": raw,
            "formatted_output": formatted,
            "returncode": returncode,
        }

    def _parse_jest(self, returncode: int, raw: str) -> dict:
        # Jest: "Tests: 3 passed, 1 failed, 4 total"
        passed = 0
        failed = 0
        total = 0

        m = re.search(r"Tests:\s+(?:(\d+) passed)?", raw)
        if m and m.group(1):
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", raw)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+) total", raw)
        if m:
            total = int(m.group(1))
        if total == 0:
            total = passed + failed

        formatted = raw[-4000:] if len(raw) > 4000 else raw

        return {
            "passed": returncode == 0 and total > 0,
            "total": total,
            "passed_count": passed,
            "failed_count": failed,
            "error_count": 0,
            "raw_output": raw,
            "formatted_output": formatted,
            "returncode": returncode,
        }

    def _extract_type_errors(self, raw: str) -> list[str]:
        lines = raw.splitlines()
        errors = [l for l in lines if ": error:" in l or "Error:" in l]
        return errors[:50]  # Cap at 50 errors

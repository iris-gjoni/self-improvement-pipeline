"""Step artifact logging and run metadata management."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class StepLogger:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def save_run_meta(self, meta: dict) -> None:
        path = self.run_dir / "run.json"
        path.write_text(json.dumps(meta, indent=2, default=str))

    def save_step(self, step_id: str, data: dict) -> None:
        # Find step index for ordering prefix
        path = self.run_dir / f"{step_id}.json"
        path.write_text(json.dumps(data, indent=2, default=str))

    def load_step(self, step_id: str) -> dict | None:
        path = self.run_dir / f"{step_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def load_run_meta(self) -> dict | None:
        path = self.run_dir / "run.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def log_event(self, event: str, data: dict | None = None) -> None:
        events_path = self.run_dir / "events.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "data": data or {},
        }
        with open(events_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

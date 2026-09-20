"""Structured evidence for a run: JSONL events + failure screenshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cuas.safety.redact import redact_dict, redact_text


class EvidenceLog:
    def __init__(self, root: Path, run_id: str):
        self.root = Path(root)
        self.run_id = run_id
        self.dir = self.root / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self._n = 0

    def write(self, event: str, **payload: Any) -> None:
        self._n += 1
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "n": self._n,
            "event": event,
            **redact_dict(payload),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def screenshot_path(self, label: str) -> Path:
        safe = redact_text(label).replace(" ", "_")[:40]
        return self.dir / f"{self._n:03d}_{safe}.png"

    def relative_dir(self) -> str:
        try:
            return str(self.dir.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(self.dir)

    def dump_text(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.write_text(redact_text(content), encoding="utf-8")
        return path

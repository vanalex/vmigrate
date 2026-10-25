from __future__ import annotations

import dataclasses
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from vmigrate.domain.models import Record


class JsonlDeadLetter:
    """Appends failed records to <dir>/<run_id>/<collection>.jsonl for inspection and replay."""

    def __init__(self, directory: str | Path):
        self._dir = Path(directory)
        self._lock = threading.Lock()

    def put(self, run_id: str, collection: str, record: Record, error: str) -> None:
        path = self._dir / run_id / f"{collection}.jsonl"
        line = json.dumps(
            {
                "ts": datetime.now(UTC).isoformat(),
                "error": error,
                "record": dataclasses.asdict(record),
            },
            default=str,
        )
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(line + "\n")

    def close(self) -> None:
        pass

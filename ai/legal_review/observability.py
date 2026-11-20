"""Record retrieval, model responses, stage timings and token counts when tracing is enabled."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from langsmith import trace


class QueryTrace:
    def __init__(self):
        self.id = uuid4()
        self.steps = []

    @contextmanager
    def stage(self, name, kind, inputs=None):
        started = time.perf_counter()
        values = {}
        entry = {"stage": name, "type": kind, "inputs": inputs or {}}
        self.steps.append(entry)
        is_root = len(self.steps) == 1
        try:
            with trace(name, run_type=kind, inputs=inputs or {}, metadata={"query_trace": str(self.id)},
                       run_id=self.id if is_root else None) as span:
                if span is not None:
                    entry["run_id"] = str(span.id)
                yield values
                if span is not None:
                    if "usage_metadata" in values:
                        span.set(usage_metadata=values["usage_metadata"])
                    span.end(outputs=values)
            entry["status"] = "ok"
        finally:
            entry.setdefault("status", "error")
            entry.update(outputs=values, seconds=round(time.perf_counter() - started, 4))
            folder = os.getenv("SAFET_LEGAL_TRACE_DIR")
            if folder and is_root:
                directory = Path(folder)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f"{self.id}.json").write_text(json.dumps(
                    {"trace_id": str(self.id), "steps": self.steps}, ensure_ascii=False, indent=2),
                    encoding="utf8")

"""Append-only audit log with a hash chain: any edit to a past record is detectable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLog:
    def __init__(self, path: Path):
        self.path, self.lock = path, Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def _records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def append(self, record: dict[str, Any]) -> str:
        with self.lock:
            records = self._records()
            prev = records[-1]["hash"] if records else "genesis"
            body = {"seq": len(records) + 1, "prev": prev, **record}
            body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(body, sort_keys=True, default=str) + "\n")
            return body["hash"]

    def get(self, record_hash: str) -> dict[str, Any] | None:
        return next((r for r in self._records() if r["hash"] == record_hash), None)

    def verify(self) -> dict[str, Any]:
        prev = "genesis"
        for r in self._records():
            body = {k: v for k, v in r.items() if k != "hash"}
            ok = (
                r["prev"] == prev
                and hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() == r["hash"]
            )
            if not ok:
                return {"valid": False, "broken_at": r["seq"]}
            prev = r["hash"]
        return {"valid": True, "records": len(self._records())}

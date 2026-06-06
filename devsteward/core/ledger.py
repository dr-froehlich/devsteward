"""The ledger: ``.devsteward/state.yaml`` (cursor) + ``.devsteward/events.jsonl`` (log).

REQ = spec, ledger = cursor. The ledger never holds requirement *content* — only the
per-step status overlay, the cursor, and parked decisions. The event log is append-only
and git-friendly; ``state.yaml`` is round-trip-stable YAML.

Design note: the :class:`StepSource` derives the step *structure* (ids, deps, verify).
The ledger owns the authoritative *status* of each step. A step absent from
``state.yaml`` defaults to ``pending``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML

from .model import Decision, DecisionStatus, StepStatus

LEDGER_DIRNAME = ".devsteward"
STATE_FILE = "state.yaml"
EVENTS_FILE = "events.jsonl"

_yaml = YAML()
_yaml.default_flow_style = False
_yaml.preserve_quotes = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    """Read/write access to a consumer project's ledger.

    Construct with the project root (the dir containing ``.devsteward/``). All paths are
    resolved relative to it so the engine works regardless of cwd.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / LEDGER_DIRNAME
        self.state_path = self.dir / STATE_FILE
        self.events_path = self.dir / EVENTS_FILE
        self._state: dict = {}
        if self.state_path.exists():
            self.reload()

    # -- lifecycle -------------------------------------------------------------

    @classmethod
    def init(cls, root: Path, profile: str = "req") -> "Ledger":
        """Create a fresh ledger under ``root/.devsteward/``."""
        ledger = cls(root)
        ledger.dir.mkdir(parents=True, exist_ok=True)
        ledger._state = {
            "version": 1,
            "profile": profile,
            "cursor": {"step": None},
            "steps": {},
            "decisions": [],
        }
        ledger.save()
        if not ledger.events_path.exists():
            ledger.events_path.touch()
        ledger.append_event("ledger_init", profile=profile)
        return ledger

    def exists(self) -> bool:
        return self.state_path.exists()

    def reload(self) -> None:
        with self.state_path.open("r", encoding="utf-8") as fh:
            self._state = _yaml.load(fh) or {}
        self._state.setdefault("steps", {})
        self._state.setdefault("decisions", [])
        self._state.setdefault("cursor", {"step": None})

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as fh:
            _yaml.dump(self._state, fh)

    # -- profile / cursor ------------------------------------------------------

    @property
    def profile(self) -> str:
        return self._state.get("profile", "req")

    @property
    def cursor_step(self) -> str | None:
        return self._state.get("cursor", {}).get("step")

    def set_cursor(self, step_id: str | None) -> None:
        self._state.setdefault("cursor", {})["step"] = step_id

    # -- step status -----------------------------------------------------------

    def status_of(self, step_id: str) -> StepStatus:
        raw = self._state["steps"].get(step_id, {}).get("status")
        return StepStatus(raw) if raw else StepStatus.PENDING

    def set_status(self, step_id: str, status: StepStatus) -> None:
        entry = self._state["steps"].setdefault(step_id, {})
        entry["status"] = status.value
        entry["updated"] = _now()

    def all_statuses(self) -> dict[str, StepStatus]:
        return {sid: self.status_of(sid) for sid in self._state["steps"]}

    # -- decisions (park-and-surface) ------------------------------------------

    def decisions(self) -> list[Decision]:
        out: list[Decision] = []
        for raw in self._state.get("decisions", []):
            data = dict(raw)
            data["status"] = DecisionStatus(data.get("status", "open"))
            out.append(Decision(**data))
        return out

    def open_decisions(self) -> list[Decision]:
        return [d for d in self.decisions() if d.status is DecisionStatus.OPEN]

    def find_decision(self, decision_id: str) -> Decision | None:
        for d in self.decisions():
            if d.id == decision_id:
                return d
        return None

    def next_decision_id(self) -> str:
        n = len(self._state.get("decisions", [])) + 1
        return f"DEC-{n:03d}"

    def park_decision(self, decision: Decision) -> None:
        """Record a parked fork and mark its step BLOCKED."""
        decision.raised_at = decision.raised_at or _now()
        decision.status = DecisionStatus.OPEN
        record = asdict(decision)
        record["status"] = decision.status.value
        self._state.setdefault("decisions", []).append(record)
        self.set_status(decision.step, StepStatus.BLOCKED)
        self.save()
        self.append_event(
            "decision_parked",
            decision=decision.id,
            step=decision.step,
            question=decision.question,
        )

    def answer_decision(self, decision_id: str, answer: str) -> Decision | None:
        """Answer a parked decision and unblock its step (back to PENDING)."""
        for raw in self._state.get("decisions", []):
            if raw["id"] == decision_id and raw.get("status") != "answered":
                raw["status"] = DecisionStatus.ANSWERED.value
                raw["answer"] = answer
                raw["answered_at"] = _now()
                step = raw["step"]
                # Only unblock if it is still blocked (don't resurrect a done step).
                if self.status_of(step) is StepStatus.BLOCKED:
                    self.set_status(step, StepStatus.PENDING)
                self.save()
                self.append_event(
                    "decision_answered", decision=decision_id, step=step, answer=answer
                )
                return self.find_decision(decision_id)
        return None

    # -- event log -------------------------------------------------------------

    def append_event(self, event: str, **fields) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {"ts": _now(), "event": event, **fields}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        out: list[dict] = []
        with self.events_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

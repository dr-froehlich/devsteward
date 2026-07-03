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

from .errors import StewardError
from .model import Decision, DecisionStatus, StepStatus

LEDGER_DIRNAME = ".devsteward"
STATE_FILE = "state.yaml"
EVENTS_FILE = "events.jsonl"

_yaml = YAML()
_yaml.default_flow_style = False
_yaml.preserve_quotes = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StaleSaveError(StewardError):
    """A blind whole-file save was refused because disk already holds newer state (REQ-073).

    The lost-update guard (``save()`` vs the on-disk ``seq``) reaches this only when the
    pending write carries **no** targeted mutation to re-apply — i.e. an engine code path
    mutated the ledger outside the ``set_status``/``set_cursor``/``park_decision``/
    ``answer_decision`` API and then dumped the whole dict (Decision 2a). Every mutation the
    engine performs in normal operation reconciles silently; this is a defect signal. The
    message is actionable: nothing was lost, both sides are preserved, re-run / report.
    """

    def __init__(self) -> None:
        super().__init__(
            "ledger save refused: a newer .devsteward/state.yaml is already on disk and this "
            "write carries no targeted mutation to reconcile — nothing was lost.",
            recovery=(
                "Nothing was lost: the newer .devsteward/state.yaml on disk and the "
                "append-only .devsteward/events.jsonl are both intact. Re-run the command; "
                "if it recurs, report it as an engine defect (a broad ledger write bypassed "
                "the targeted-mutation API). Never hand-edit state.yaml."
            ),
        )


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
        # REQ-073 lost-update guard: the `seq` this instance last synced with disk, and a
        # journal of *this process's own* targeted mutations since the last save (replayed
        # onto the newer on-disk state if a concurrent save moved `seq` under us).
        self._loaded_seq: int | None = None
        self._journal: list = []
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
        # A legacy state.yaml predating REQ-073 has no `seq` — load as None, upgrade on save.
        self._loaded_seq = self._state.get("seq")

    def _disk_seq(self) -> int | None:
        """The `seq` currently on disk, or None (missing file, or a legacy pre-`seq` state)."""
        if not self.state_path.exists():
            return None
        with self.state_path.open("r", encoding="utf-8") as fh:
            data = _yaml.load(fh) or {}
        return data.get("seq")

    def save(self) -> None:
        """Persist ``state.yaml`` without ever blind-overwriting newer on-disk state (REQ-073).

        A monotonic ``seq`` guards the write. If disk carries a ``seq`` newer than the one
        this instance loaded, a concurrent process saved under us — the blind whole-file dump
        would rewind its committed facts. Instead we **reconcile**: reload the newer state and
        replay this process's own targeted-mutation journal onto it (re-applying just our
        mutation, leaving every unrelated newer fact intact). A pending write with an **empty**
        journal cannot be reconciled — a broad, non-targeted dump (an engine defect) — so it
        **fails loudly** with both the on-disk state and the event log preserved.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        disk_seq = self._disk_seq()
        if disk_seq is not None and disk_seq > (self._loaded_seq or 0):
            if not self._journal:
                raise StaleSaveError()
            journal = list(self._journal)
            self.reload()  # adopt the newer on-disk state (refreshes _loaded_seq)
            for apply in journal:
                apply(self._state)
        self._write_state()

    def _write_state(self) -> None:
        next_seq = (self._loaded_seq or 0) + 1
        self._state["seq"] = next_seq
        with self.state_path.open("w", encoding="utf-8") as fh:
            _yaml.dump(self._state, fh)
        self._loaded_seq = next_seq
        self._journal.clear()

    # -- profile / cursor ------------------------------------------------------

    @property
    def profile(self) -> str:
        return self._state.get("profile", "req")

    @property
    def cursor_step(self) -> str | None:
        return self._state.get("cursor", {}).get("step")

    def set_cursor(self, step_id: str | None) -> None:
        def apply(state: dict) -> None:
            state.setdefault("cursor", {})["step"] = step_id

        apply(self._state)
        self._journal.append(apply)

    # -- step status -----------------------------------------------------------

    def status_of(self, step_id: str) -> StepStatus:
        raw = self._state["steps"].get(step_id, {}).get("status")
        return StepStatus(raw) if raw else StepStatus.PENDING

    def set_status(self, step_id: str, status: StepStatus) -> None:
        updated = _now()

        def apply(state: dict) -> None:
            entry = state.setdefault("steps", {}).setdefault(step_id, {})
            entry["status"] = status.value
            entry["updated"] = updated

        apply(self._state)
        self._journal.append(apply)

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

        def apply(state: dict) -> None:
            state.setdefault("decisions", []).append(dict(record))

        apply(self._state)
        self._journal.append(apply)
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
        target = next(
            (
                raw
                for raw in self._state.get("decisions", [])
                if raw["id"] == decision_id and raw.get("status") != "answered"
            ),
            None,
        )
        if target is None:
            return None
        step = target["step"]
        answered_at = _now()
        updated = _now()

        def apply(state: dict) -> None:
            for raw in state.get("decisions", []):
                if raw["id"] == decision_id:
                    raw["status"] = DecisionStatus.ANSWERED.value
                    raw["answer"] = answer
                    raw["answered_at"] = answered_at
                    break
            # Only unblock if it is *still* blocked in the state we are writing — never
            # resurrect a step a concurrent land already carried to DONE (REQ-073 replay).
            entry = state.get("steps", {}).get(step)
            if entry and entry.get("status") == StepStatus.BLOCKED.value:
                entry["status"] = StepStatus.PENDING.value
                entry["updated"] = updated

        apply(self._state)
        self._journal.append(apply)
        self.save()
        self.append_event(
            "decision_answered", decision=decision_id, step=step, answer=answer
        )
        return self.find_decision(decision_id)

    def reconcile_validation_decision(self, decision_id: str) -> Decision | None:
        """Close a lingering open ``:validate`` decision against the event log — the D2
        recovery (REQ-073 Decision 3/5).

        A ``done`` REQ that still surfaces an open ``:validate`` decision is self-evidently
        resolvable: the land already happened and is in the event log. Closing it touches
        **only** the decision record (status → answered with a reconciliation note) and
        appends a ``decision_reconciled`` event — the step status, ``verified_by`` and the
        frozen landing provenance stay untouched (REQ-035). Returns the reconciled decision,
        or None if there is no matching open one.
        """
        target = next(
            (
                raw
                for raw in self._state.get("decisions", [])
                if raw["id"] == decision_id and raw.get("status") != "answered"
            ),
            None,
        )
        if target is None:
            return None
        step = target["step"]
        answered_at = _now()

        def apply(state: dict) -> None:
            for raw in state.get("decisions", []):
                if raw["id"] == decision_id:
                    raw["status"] = DecisionStatus.ANSWERED.value
                    raw["answer"] = (
                        "reconciled against the event log (the land already happened)"
                    )
                    raw["answered_at"] = answered_at
                    break

        apply(self._state)
        self._journal.append(apply)
        self.save()
        self.append_event("decision_reconciled", decision=decision_id, step=step)
        return self.find_decision(decision_id)

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

    def latest_validation(self, req_id: str) -> dict | None:
        """The most recent ``validation`` event for ``req_id`` (or ``None``).

        The rework verb (REQ-033) reads it to tell a real red — an artifact red or a
        *declined* manual sign-off, both of which record a ``validation`` event with
        ``ok: false`` then park — from an *awaiting-oracle* manual park (which records no
        validation event) or a green/never-run validation.
        """
        latest: dict | None = None
        for ev in self.events():
            if ev.get("event") == "validation" and ev.get("req") == req_id:
                latest = ev
        return latest

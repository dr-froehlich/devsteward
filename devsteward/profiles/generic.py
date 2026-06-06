"""The generic profile — an explicit, content-agnostic step list.

This is the "run any Claude automation" mode: the ledger itself carries the steps (id,
command, deps, verify), and the executor walks them with no knowledge of requirements.
Used for non-REQ automation and as the minimal proof that the core is truly generic.
"""

from __future__ import annotations

from ..core.model import Step


class GenericStepSource:
    """A :class:`StepSource` reading an explicit step list from ``state.yaml``.

    The list lives under a top-level ``plan:`` key in ``state.yaml``::

        plan:
          - id: gather
            command: "/intake gather the inputs"
          - id: write
            command: "/intake write the draft"
            depends_on: [gather]
            verify: ["pytest tests/test_draft.py"]
    """

    def steps(self, ledger) -> list[Step]:
        plan = ledger._state.get("plan", [])  # noqa: SLF001 — ledger owns the doc
        out: list[Step] = []
        for item in plan:
            out.append(
                Step(
                    id=str(item["id"]),
                    command=str(item.get("command", "")),
                    depends_on=tuple(item.get("depends_on", ()) or ()),
                    verify=tuple(item.get("verify", ()) or ()),
                    title=str(item.get("title", "")),
                )
            )
        return out

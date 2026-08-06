# Plan — REQ-001: bring {{PROJECT_NAME}} to life

The plan artifact for [REQ-001](../requirements/REQ-001.md), the north star. `/bootstrap`
fills this in from the interview; the engine's land gate refuses to land a REQ that no plan
names, and the bootstrap session is REQ-001's develop session like any other.

Keep it short. This records what was *chosen* at project birth, so a reader a year from now
knows which decisions are original and which were made later.

## What this project is

{{PROJECT_DESCRIPTION}}

## Stack

{{STACK}}

## Commands

| | |
|---|---|
| Build | `{{BUILD_COMMAND}}` |
| Test  | `{{TEST_COMMAND}}` |

These are also recorded in `.devsteward/config.yaml`, where the develop gate runs the test
command as `verify.full_suite` for every REQ from REQ-002 onward.

## Approach

The skeleton is stamped, not built: `steward new` laid down the scaffolding, `/bootstrap`
filled the placeholders, and REQ-001's acceptance criterion checks that the initialization
is coherent — not that the project does anything yet. Everything the project actually does
begins at REQ-002.

## Notes

Replace this section with anything worth remembering about how the project started:
rejected alternatives for the stack, constraints that shaped the layout, deployment targets
that are already fixed.

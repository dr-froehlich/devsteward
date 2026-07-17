# DevSteward

A controlled baseline for starting Claude Code projects, plus the automation engine
that drives them. One public, pipx-installable package that bundles both the **engine**
(the `steward` CLI) and the **scaffolding** it stamps into new projects.

DevSteward captures a proven, evolved house style — REQ-per-file requirements with a
machine-readable contract, a frozen `REQ-001` north star, a dependency-ordered
`depends_on` graph, and an attended/unattended automation loop that walks the work and only marks a step
done when its named acceptance tests pass.

## Install

```sh
pipx install git+https://github.com/.../devsteward@v0.1.0
```

Pin a tag. Consumer projects pin a `devsteward` version the same way `material` pins
`material-core`.

## Use

```sh
steward new ../my-project     # stamp the bundled scaffolding into a new consumer repo
steward lint                  # schema-validate REQs; deps resolve; index↔REQ in sync
steward status               # show the ledger cursor and what's eligible next
steward advance              # attended: do exactly one checkpoint, interactively
steward run                  # unattended: march eligible steps headless; park on forks
steward decision list        # show parked decisions raised while unattended
steward decision answer DEC-001 "..."
```

## The model

A **generic executor core** walks a ledger of steps in dependency order, invokes
`claude -p "<command>"` headless for each, verifies the result against named tests,
commits, and advances the cursor. A swappable **REQ-workflow profile** sits on top and
derives those steps from the REQ files as a Design → Build → Land cycle.

Verification and fork-handling (*park-and-surface*) are owned by the **engine**, not the
skill — so unattended automation can't be talked into a false "done".

See `devsteward/handbook/` for the full reference, and `docs/requirements/` for
DevSteward's own requirements (dogfooded in the format it ships).

## Develop

```sh
pipx install --editable .
python -m pytest
```

DevSteward dogfoods itself: its own requirements live in `docs/requirements/` in the
hybrid machine-readable format, and its own ledger lives in `.devsteward/`.

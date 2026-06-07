# 00 · The method

DevSteward captures one developer's proven, evolved house style for running software
projects with Claude Code and makes it reproducible. It exists because the alternative —
copying the most recent project as a reference — lets the method drift and good ideas
fail to propagate. DevSteward is the single controlled baseline.

## The shape of the method

1. **Requirements are the unit of work.** Each is one file with a machine-readable
   contract (YAML frontmatter + an acceptance block) and rich prose (Context, Decisions,
   Notes). See [01 · The format](01-format.md).
2. **REQ-001 is a frozen north star.** Direction changes by *superseding* it with a new
   REQ, never by quietly weakening it.
3. **A dependency DAG orders the work.** `depends_on` makes a REQ eligible only once its
   prerequisites are done. `ROADMAP.md` is the human view of that graph.
4. **An engine walks the work.** One checkpoint at a time (`steward advance`) or marching
   every eligible step (`steward run`) — both headless, parking forks. A human can also
   drive `/advance` interactively, trading the engine's guarantees for the loop. See
   [02 · The engine](02-engine.md).
5. **Verification is mechanical.** Acceptance criteria name runnable tests; a step is
   done only when they are green — checked by the engine, not asserted by a model.

## First-class conventions

These are not style preferences; the linter and the engine enforce them.

- **English everywhere** in code and technical docs. Localized UI strings are allowed but
  isolated and translatable — never inline in logic.
- **Same-commit discipline.** A REQ's frontmatter, its `REQUIREMENTS_INDEX.md` row, and
  the code that satisfies it move together, in one commit.
- **Branch before main.** Never commit directly to `main`.
- **Co-author trailer** on every commit.
- **Sanitized public artifacts.** No real local paths, emails, or credentials in shared
  files; templates use placeholders.

## The two-repo pattern

DevSteward ships as one public, pipx-installable package (the `material-core` pattern):
the **engine** (`steward` CLI) and the bundled **scaffolding** ride in the same wheel.
**Consumer projects** are private, pin a `devsteward` tag, and hold the real data. A
consumer is created by `steward new` (or the `/bootstrap` skill, which wraps it with an
interview).

# REQ-097 concept — the status dashboard, frozen

**Frozen: 2026-09-17, with Peter (attended develop session, concept phase per REQ-097
Decision 2).** The deliverable is the committed prototype itself — the `devsteward.dashboard`
package, its three pages and the `steward dashboard` verb — wired into the engine by this
same REQ (REQ-067's committed-prototype form). This document records what was frozen, what
the spike found, and what was rejected on the way, so the target acceptance criteria written
after the freeze (AC8–AC10 in the REQ) have their reasoning next to them.

The owner's verdict on the first live render over all seventeen project folders on the
development box: *"Can't see anything amiss, therefore: freeze."* No change request was
raised; the page inventory below is therefore the one that was looked at.

## 1. The frozen page inventory

Three pages, one per altitude. Every value on them is derived at request time from the
working tree the sessions use — nothing is cached, nothing is stored.

**Overview (`/`)** — the box.

- A **needs-me strip** first: everything across all projects that waits on the operator,
  one row each — a parked fork (`decision`), a validate step held or eligible
  (`validation`), a FAILED step (`failed`), an attended develop step (`attended`) — with
  the project, the step, the note, and the command that is the operator's move.
- A **projects table**: one row per stamped project — branch (with a *no remote* badge),
  dirty path count, unpushed commits on the integration branch, the integration → production
  gap, last commit age with short sha and subject, the derived steward steps with their
  CLI marks and an *eligible* badge, a parked-fork count, a drift warning, and the backlog
  state counts.
- An **unstamped list**: child folders without a `.devsteward/` ledger, for information only.

**Project (`/p/<name>`)** — one project.

- The **git facts** line (Decision 8's six facts).
- **Steward status**: profile and cursor, then the step table with the CLI's marks, the
  hold/blocked note, and an **action** cell that offers exactly the CLI's recovery verbs
  where they apply — `repeat` on a FAILED step (`reland` too when a green validation was
  followed by a land refusal), `rework`/`revalidate` on a validate step blocked on a red
  validation — or names the command the operator must run themselves (`steward validate
  REQ` for a held or eligible validation, `/advance REQ develop` for an eligible develop
  step). Parked forks follow, each with its brief and an answer form (`decision-answer`).
  Stamped-artifact drift is listed with the `steward sync` hint.
- **Requirements**: the index newest first, terminal REQs dimmed, each id linking to its
  page; a draft (or dropped) REQ gets an `activate` button.
- **Backlog**: the items with their derived state badge (`open (denied N×)` etc.), need,
  criteria, origin, take-up links and verdict history; per item an **edit** form (need,
  origin, criteria one per line — `backlog-edit`) and a **verdict** form (accept / deny /
  hold / retire with reason or note — the four verdict verbs), both folded; an **add** form
  at the bottom (`backlog-add`).

**REQ (`/p/<name>/req/<id>`)** — read-only: the frontmatter as a table, the acceptance
block as a table (id, check, status, criterion, test), then the prose rendered from
Markdown with the acceptance fence removed so nothing is shown twice. No form, no write
route.

Every write flashes the outcome in the CLI's own words; a refusal flashes the CLI's refusal
text in red. The page never spawns a session: the batch verbs have no route.

## 2. Architecture as built

```
devsteward/verbs.py                 one body per state-changing verb: build the executor, run
                                    check_invariants exactly as the CLI did, mutate inside the
                                    transaction boundary; CLI commands and dashboard routes both
                                    call these — REQ-097 Decision 5 made concrete
devsteward/profiles/req/backlog.py  + bits / add / edit / set_criteria / record_verdict: the
                                    backlog file operations, one body per backlog verb
devsteward/dashboard/model.py       pure reads: scan_root, project_status (what `steward status`
                                    prints, as data), git_facts (read-only porcelain), attention
                                    (needs-me), load_project, req_body_html — no web framework
devsteward/dashboard/app.py         Flask: three GET pages, POST handlers that call verbs/backlog
                                    under one lock and redirect with a flash; loopback only
devsteward/dashboard/templates/     base / overview / project / req (Jinja, inline CSS, no CDN)
devsteward/cli.py                   `steward dashboard [--root] [--port]`, `steward backlog-edit`
```

**The CLI became a printer.** `activate`, `repeat`, `rework`, `revalidate`, `reland` and
`decision-answer` in `cli.py` now call `devsteward.verbs`; `backlog-add`/`-list`/the four
verdicts call the new functions in `backlog.py`. This is the refactor Decision 5 implied:
"the same functions the CLI verbs call" is only true if there *is* one function per verb.
Behaviour is unchanged — the existing verb tests pass untouched.

**Actions are offered by cheap signals; the engine decides.** `_offer()` mirrors the hints
`steward status` already prints (a FAILED step names `repeat`; a red validation names
`rework`/`revalidate`; a manual hold names `steward validate`). The offer is display only:
the verb's own precondition runs when the button is pressed, and a refusal renders the CLI's
message. Duplicating the preconditions into the page would have been a second copy with no
writer when the state machine changes (which `simpler-state-changes` will do).

## 3. What the spike found

1. **One page load parsed every REQ six times.** Profiling the first render (11.5 s for
   the overview, 5.2 s for the largest project page) showed `load_reqs` called six times per
   project — by `build_executor` (the verifier's node-id derivation), by `steps()`, by
   `eligible_steps()` (which calls `steps()` again), and by the model's own reads. Each
   parse is ruamel round-trip YAML at ~3 ms, and the largest project has 173 REQs. The cure
   is a seam, not a cache: `ReqStepSource(req_dir, reqs=…)`, `build_executor(cfg, reqs=…)`
   and `backlog.bits(cfg, reqs=…)` accept an already-parsed corpus; every CLI path leaves
   it `None` and reads from disk exactly as before. Overview 11.5 s → 2.4 s, largest
   project 5.2 s → 1.0 s. AC10 pins the property (one parse per REQ file per page load).
   A cross-request cache keyed on mtime was considered and *not* built: 2.4 s for
   seventeen projects was judged acceptable, and a cache is a second copy.
2. **Markdown joined the extra.** A REQ page in raw text loses the Decisions table, which
   is the part worth reading. Python-Markdown (`tables`, `fenced_code`) renders it; the
   extra is therefore `flask` + `markdown`, both absent from the bare package. Without
   `markdown` the page falls back to `<pre>`; without `flask` the verb refuses with the
   install hint.
3. **`StopController` cannot live in a request thread.** `reland` installs signal handlers
   in the CLI; `verbs.reland` takes `stop=None` so the dashboard's call installs nothing.
4. **Writes are the operator's second-shell writes** (Decision 11) — serialized under one
   lock in the app so two clicks cannot interleave, exactly as one shell serializes them.

## 4. Rejected on the way

- **A sibling tool** (the clauder shape, REQ-058): would have needed a machine-readable
  status seam from devsteward first — two repos for one feature (REQ Decision 1).
- **Stdlib `http.server`**: feasible for a loopback tool, but the iteration the concept
  phase needed (three pages, forms, flashes) is what a micro-framework exists for, and the
  extra keeps it off every consumer's install (Decision 3).
- **Docker / a LAN host / a service unit**: the deployment interview settled a plain
  on-demand process (Decision 4); nothing named needed isolation or 24/7.
- **Pre-computing preconditions in the page**: see §2 — a second copy.
- **Editing REQs from the page**: Decision 10; a REQ moves with its code in one commit.
- **A `--open` flag** that launches the browser: on WSL2 it would need a Windows-side
  launcher; printing the URL was enough for the owner. Not built.

## 5. What the build does after the freeze

The prototype *is* the build; what remained after the freeze was bookkeeping: the plan,
the manual rows (`dashboard`, `backlog-edit`), the handbook line, the acceptance tests for
AC1–AC7 (the mechanism) and AC8–AC10 (the frozen pages and the one-parse property), and the
checkpoint. The `simpler-state-changes` item is untouched — the action cell will follow
whatever verbs the CLI has when that REQ lands, because it only names the CLI's verbs.

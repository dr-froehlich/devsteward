# REQ-088 — Kill the suite's random reds

Covers **REQ-088**. Two independent engine defects, both now diagnosed, plus the removal of
the workarounds they grew.

## Cause A — the evidence-dir mint collides with itself

**Confirmed by inspection + a live failure.** `validate._now_stamp()` is
`strftime("%Y%m%dT%H%M%SZ")` — second granularity. Both mint sites (`validate.py:377` in the
start half, `validate.py:639` in the full run) build
`.devsteward/evidence/<REQ>/<stamp>/` and `mkdir(..., exist_ok=True)`, so a second validation
starting inside the same wall-clock second silently **aliases** the first one's directory.
`_carry_forward` then walks the source evidence dir and copies each file to a destination that
is now the file itself:

```
SameFileError: …/evidence/REQ-001/20260806T050731Z/capture.txt
           and …/evidence/REQ-001/20260806T050731Z/capture.txt are the same file
```

### Fix

One shared `_mint_evidence_dir(root, req_id)` helper used by both sites:

- stamp extended to microsecond precision — `%Y%m%dT%H%M%S_%fZ` → `20260806T050731_482913Z`;
- created with `exist_ok=False`, so two validations can never alias one directory. Aliasing is
  the defect; `exist_ok=True` is what made it silent. A genuine collision now fails loudly
  instead of corrupting the carry (per REQ-088 Decision 3 — no collision-suffix retry loop).

Recorded history keeps working: evidence paths are read back **literally** from
`events.jsonl` (`_resolve_start_context`, `_carry_forward`), never re-derived from a stamp
format, so second-granular paths already on disk in FlowSteward / memzy / THermo still resolve.
No migration.

## Cause B — the land drops its own flip (mechanism now confirmed)

Previously unproven. Pinned during this session with an instrumented run; the decisive dump,
taken immediately before the land's `git add -A`:

```
cached REQ index entry : mtime 1785994308:402866240   size 412
worktree REQ-001.md    : mtime 1785994308.680900      size 412
index file             : mtime 1785994320.336700
staged at commit       : []
```

Three conditions coincide, and all three are structural rather than unlucky:

1. **The flip is size-preserving.** `status: open` → `status: done` and `| OPEN |` → `| DONE |`
   are both 4 bytes either way, so the file's size never changes.
2. **The flip lands in the same wall-clock second as the stat git has cached** for that path
   (cached by `_capture_gap`'s `_stage_code`, which stages the whole tree before `on_verified`
   writes the flip). Git is built without `USE_NSEC` by default, so it compares only
   *seconds* + size — and both match.
3. **Git's racy-clean safety net does not fire.** It only content-checks an entry whose cached
   mtime is `>=` the index file's own timestamp. Here the index was written 12s later (the
   capture-gate extract runs pytest in between), so the entry looks non-racy and git trusts the
   stat comparison.

Result: `git add -A` stages **nothing**, the flip misses its own commit, and REQ-077's
`_assert_committed_clean` rolls the land back. The guard is correct; it is the only thing
standing between this and a silently inconsistent history.

This is why the naive shell reproduction (`add -A`; rewrite; `add -A`) never reproduced: there
the index is written in the *same* second as the file, so the entry **is** racy, git smudges it
and content-checks it. The 12-second capture-gate gap is load-bearing.

### Fix

At the second stage the only newly-dirty paths are exactly the ones `on_verified` just wrote —
`_capture_gap`'s stage already picked up everything else. `ReqDoneFlipper.__call__` already
**returns** those paths (`{req.path, index_path}`); the executor currently discards the return
value. So:

- `_land_checked` keeps `on_verified`'s returned paths and hands them to `_commit`;
- `GitCli._stage_code(force=…)` follows the whole-tree `git add -A` with
  `git add --renormalize -- <those paths>`. `--renormalize` re-reads content and bypasses the
  stat shortcut entirely.

Measured against a deterministically forced coincidence (`os.utime` pins the flip to the cached
second and pushes the index timestamp past it):

| staging strategy | result |
|---|---|
| `git add -A` (today) | **MISS** — staged nothing |
| `git add --renormalize` on the written paths | **PASS** |
| `git update-index --really-refresh` then `git add -A` | MISS |

Scoped to the engine's own writes deliberately: repo-wide `--renormalize` would re-run clean
filters over every tracked file and could stage unrelated line-ending normalization in a
consumer repo. Anything outside `on_verified`'s paths stays covered by REQ-077's guard, which
fails loudly rather than silently. This is not a narrow band-aid: at the second stage those
*are* the only newly-dirty paths, because the capture gate's stage already took everything else.

Two properties the fix must not break, both tested:

- **Additive only.** `force_paths` can never restrict the commit — naming one path still commits
  the whole dirty tree. REQ-079's AC1 guard was an exact-signature assertion
  (`["self", "message"]`); it is restated as the invariant it actually names ("no
  baseline/include/exclude/only/scope parameter") plus a behavioural widening test, so it keeps
  its teeth against a return of REQ-076's scoping without banning an additive keyword.
- **Absent paths are tolerated.** `git add --renormalize` treats an unmatched pathspec as fatal
  (exit 128), so a `force_paths` entry that does not exist — a project with no index file — would
  turn a benign absence into a hard land failure. `_stage_code` filters to existing paths.
  An untracked path is fine (`--renormalize` is a no-op over it; the whole-tree add already
  staged it).

### Considered and rejected

- **A temporary `GIT_INDEX_FILE` for the capture gate**, so the read-only self-check never
  poisons the real index's stat cache. Conceptually the tidier root fix, but it is a larger
  change to a REQ-063 invariant (the checked tree must be built by the same staging routine the
  commit uses) and it does not cover a session that writes a file twice, size-preserving, inside
  one second. Not worth the topology.
- **Touching the flip files' mtime forward** after writing them. Defeats the stat cache but is a
  timing hack that breaks at a second boundary.

## Work items

1. `validate.py` — `_now_stamp()` to microseconds; one `_mint_evidence_dir` helper; both sites.
2. `seams.py` / `git.py` / `executor.py` — thread `on_verified`'s written paths into the stage.
3. `conftest.py` fake — accept the new keyword.
4. `tests/test_req088_evidence_mint.py` — AC1, AC2, AC3 meta-guard.
5. `tests/test_req088_land_soak.py` — AC5 deterministic mechanism test, AC4 soak.

   The soak is sized by **cost**, not detection power. Measured against a deliberately
   un-fixed engine, 30 lands (~23s) catch the known Cause-B mechanism about **1 run in 5** —
   it cannot force the wall-clock-second coincidence. AC5's forced test is the real oracle;
   the soak is the standing bound on the invariant and on residual undiagnosed causes.
   Raising it buys little (60 lands ≈ double cost, still well under half detection).
6. Subtract the workarounds: both `time.sleep(1.1)` in `tests/test_req081_halves.py`; mark the
   REQ-087 Notes + plan flake caveat superseded.

# REQ-102 — A non-governed repository joins joint tasks

Plan for `REQ-102:develop`. Requirement: `docs/requirements/REQ-102.md` (8 decisions,
4 regression ACs, no concept phase, no System-Test phase).

## The shape of the change

| Piece | Where | What |
|---|---|---|
| the role | `devsteward/config.py` | `JOINT_PROFILE = "joint"` and `Config.joint_only`. The `profile` seam already says what kind of project a folder is (Decision 1). |
| joining | `cli.py: new` | `--profile joint` writes only `.devsteward/config.yaml`. No stamp, no ledger, no lock, no `--force` needed. Refuses when `.devsteward/` exists (Decision 3). |
| leave it alone | `cli.py: _load_or_die(joint=False)` | Every verb that loads the project refuses on a joint-only participant unless it passes `joint=True`. Only `status`, `lint`, `sync` and the four joint verbs do. Refusing by default means a REQ verb added later is safe without anyone remembering this REQ. |
| | `cli.py: status / lint / sync` | A joint-only branch, taken before anything reads a ledger, REQ corpus or template tree (Decision 2). |
| dashboard | `dashboard/model.py`, `app.py`, `overview.html`, `project.html` | `ProjectView.joint_only`. `load_project` stops after config and git facts. The pages show "joint-only participant" in place of status, backlog and requirements. The write routes 404 for it. |
| take-up | `profiles/req/joint.py`, `cli.py: joint-ack` | `filed_as` on an `ack` of the `action`. `Thread.filed_as`, the candidate rule and the order in `take_up` (Decision 4). |
| manual | `templates/STEWARD.md`, `handbook/_01-format.qmd` | the joint-only participant, `new --profile joint`, `--filed-as` |
| tests | `tests/test_req102_joint_only.py` | AC1–AC4 |

The shipped skills do not change (Decision 5).

## Details

- **The refusal text**, one line: `<name> is a joint-only participant (profile: joint):
  'steward <verb>' belongs to the REQ workflow, which does not run here — joint tasks: steward
  joint-list`. It is a `ClickException`, so the exit is non-zero and nothing is written.
- **`status`**: `profile: joint`, then `<name> is a joint-only participant: it takes part in
  joint tasks (steward joint-list) and runs no REQ workflow.` No drift block.
- **`lint`**: `lint: OK (joint-only participant — no REQ corpus to lint)`.
- **`sync`**: `joint-only participant — no engine-owned artifacts are stamped here.` Nothing is
  written, not even a lock.
- **`new --profile joint`**: it creates TARGET if absent. The config carries a two-line comment
  saying what it is (a joint-only participant, REQ-102) and that nothing else of the engine's
  belongs here, then `profile: joint`.
- **`filed_as`** is an optional string on any `Entry`, serialised only when set. `_entry`
  rejects a non-string.
- **`ack(cfg, handle, ref, filed_as=None)`**:
  - With `filed_as`, the `ref` must be the thread's `action`, otherwise `JointError`.
  - If the receiver already wrote an `ack` of the action: the same `filed_as` → no-op (`None`);
    anything else → `JointError` ("an acknowledgement is never changed").
  - An earlier *reply* to the action (an `ask` sent before filing) does not block filing.
  - Without `filed_as`, behaviour is REQ-101's.
- **`Thread.filed_as`** is the `filed_as` of the addressee's first `ack` of the action that
  carries one.
- **`candidates`**: open requests to me whose handle is not in my backlog **and** whose
  `filed_as` is unset.
- **`take_up`**, in this order:
  1. the addressee has a backlog item with the handle → REQ-101's derivation (unchanged);
  2. `thread.filed_as` → `filed as <ref>`;
  3. otherwise `not taken up by <addressee> yet`.

  It reads the addressee's backlog with `bl.load` on its config. A joint-only addressee has no
  backlog file, so it falls through.

## Tests (`tests/test_req102_joint_only.py`)

The fixture is a temp root. `sarah` is stamped like REQ-101's fixture, with a backlog created
by `backlog-add`. `system-admin` is a git repo with a README, a `log/` file and an `open.md`,
joined through the real `steward new --profile joint`.

- **AC1** `test_joining_writes_only_the_declaration_and_the_req_workflow_leaves_it_alone`:
  - snapshot system-admin, run `new --profile joint` without `--force`, and diff: the only new
    path is `.devsteward/config.yaml`, and it holds `profile: joint`;
  - a second run refuses;
  - `status` names the joint-only participant and has no "sync" text, `lint` exits 0, and `sync`
    leaves the tree identical;
  - `advance`, `checkpoint`, `activate` and `backlog-add` each exit non-zero naming
    `profile: joint`, with the tree identical afterwards.
- **AC2** `test_the_dashboard_lists_a_joint_only_participant_without_req_sections`:
  - `model.load_project` gives `joint_only`, git facts, no status, backlog, requirements or
    attention;
  - the Flask overview lists it, marked joint-only, and its project page renders with no
    "Steward status", "Backlog" or "Requirements" heading and no form;
  - a POST to its verb route is 404.
- **AC3** `test_a_governed_project_and_a_joint_only_participant_work_a_thread_both_ways`: the
  two directions from the REQ. The governed side uses only REQ-101 options.
- **AC4** `test_filed_as_is_only_the_requests_acknowledgement_and_take_up_follows_its_order`:
  - `--filed-as` on an ack of a `tell` is refused, and so is `--filed-as` on an action already
    acked without one;
  - `joint-show` prints `not taken up by …` before any take-up, then `filed as …`;
  - for a governed addressee, a backlog item wins over a `filed_as`.

## Develop obligations outside the gate

- **STEWARD.md and the handbook** in the same commit (REQ-094).
- **The live proof** (REQ-102 *Live proof*). It needs the owner's go to join system-admin, and the
  owner's attended system-admin and sarah sessions.

## The live proof: what happened (2026-10-10)

The live proof ran in the real repositories. The owner gave his go to join system-admin and drove
the system-admin and sarah sessions.

| # | Where | What happened | Verdict |
|---|---|---|---|
| 1 | system-admin | `steward new ~/projects/system-admin --profile joint` wrote only `.devsteward/config.yaml`. In place, `status` named a joint-only participant with no sync lines, `lint` was OK, `sync` wrote nothing, and `advance` refused in one line. The dashboard model and page showed the badge and git facts, with no REQ sections and no forms. | as designed |
| 2 | devsteward | It opened `devsteward-adopt-joint-tasks` (`devsteward#1`). system-admin's `joint-list` showed it as waiting and as a request to take up. Its header said "not yet in this project's backlog", which is wrong for a project that keeps none. | **fixed in place**: the header now tells a joint-only participant to take it up with `joint-ack … --filed-as` |
| 3 | system-admin | Taken up by hand with the verbs: filed as **OPEN-0184** and acknowledged `--filed-as OPEN-0184` (`71d6dc0`). devsteward's `joint-show` read *"filed as OPEN-0184 by system-admin"*. | as designed |
| 4 | system-admin | Built its stand-in, `.claude/skills/joint-tasks/SKILL.md` (`b8fdf90`, LOG-0307/0308), and changed `open.py handover` to send one joint task per item to a stamped owner (`1e16a3b`, OP9, AC35, LOG-0309). | system-admin's own work, under its own rules (Decision 6) |
| 5 | system-admin → devsteward | `system-admin#4`, a `tell`: devsteward's request wrote the handle as `--handle`, but `joint-send` takes it as its argument. system-admin's first handover was refused and sent nothing. It corrected its call (`7ca352e`). | **defect in devsteward's request text**, also in REQ-102 Decision 7 and AC3's text. The text was corrected and the verb left as it was. devsteward answered with `devsteward#2`, and system-admin acknowledged it (`b9d4f10`) |
| 6 | system-admin → sarah | OPEN-0180 and OPEN-0183 went out through the new handover as `sysadmin-open-0180` and `sysadmin-open-0183`. The body carries what the old handover file inlined. | as designed |
| 7 | sarah | Its unchanged `/intake` (REQ-101 skills) filed both under system-admin's handles, with criteria from each item's *Closes when*, and acknowledged both. system-admin's `joint-show` read *"open — filed in sarah's backlog, no REQ yet"*. | as designed: the governed side saw no difference |

**Not closed within develop (Decision 8, as amended).** The adoption thread's two `done`s wait on
OPEN-0184. That item closes when *"a request from a devsteward project has been taken up through
the skill"*, and no stamped project had sent system-admin a request since the skill existed. The
owner chose to close REQ-102 on what was proven. The thread stays open in devsteward's and
system-admin's `joint-list` until a real request arrives and both send `done`. devsteward's own
half of this thread is real, so it is committed with REQ-102.

"""REQ-080 — ``steward run`` rides through a budget limit instead of quitting.

Observed in FlowSteward REQ-116 (2026-07-16): a headless session died on a usage limit, the
ledger recorded ``step_failed outcome=error`` (the ending missed ``_LIMIT_MARKERS``), the run
stopped, and ~2h of unattended time was lost to a window the engine could have waited out.
Two gaps behind that one failure, plus a rider:

* the death was **misclassified** — an ERROR sets the step FAILED, a stopping state needing a
  manual ``steward repeat``; a limit would merely have requeued it;
* the run **stops even on a correct limit** — ``Executor.run`` broke out on ``RunOutcome
  .LIMIT``, though ``precheck`` → ``clauder gate`` already knows how to wait and re-gate;
* the requeue dropped the **recovery signal**, so a relaunch would start clean over a dirty
  tree of the killed session's partial edits.

Everything here drives the real ``Executor``/``ClauderAccountProvider`` against a fake runner
and a fake ``clauder gate`` (a scripted ``subprocess.run``) — a real budget limit cannot be
provoked on demand (REQ-080 Decision 7), so the seams are the oracle. No network, no service,
no secret: self-contained in a clean checkout.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from devsteward.core import accounts, claude as claude_mod
from devsteward.core.accounts import BudgetVerdict, SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus

from conftest import FakeGitTopology, ListStepSource, RecordingCommitter, ok_result

# -- fakes ---------------------------------------------------------------------

#: clauder's gate exit codes (clauder/gate.py) — the verdicts this REQ reacts to.
PROCEED = (0, {"decision": "proceed", "reason": "proceed-active"})
SWITCH = (0, {"decision": "switch", "account": 2, "reason": "switch-to-2"})
WAIT = (75, {"decision": "wait", "wait_seconds": 3600, "reason": "soonest-reset"})
UNSATISFIABLE = (69, {"decision": "unsatisfiable", "reason": "exceeds-pool"})


def _gate_run(scripted, calls=None):
    """A ``subprocess.run`` stand-in for ``clauder gate``: returns each scripted
    ``(rc, body)`` in turn (the last repeats), recording each argv into ``calls``."""
    state = {"i": 0}

    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        rc, body = scripted[min(state["i"], len(scripted) - 1)]
        state["i"] += 1
        return SimpleNamespace(returncode=rc, stdout=json.dumps(body), stderr="")

    return run


def _clauder(monkeypatch, scripted, *, calls=None, slept=None, should_stop=None,
             present=True):
    """A :class:`ClauderAccountProvider` over a fake gate. ``present=False`` takes clauder
    off PATH (the degradation case)."""
    monkeypatch.setattr(
        accounts.shutil, "which", lambda name: "/usr/bin/clauder" if present else None
    )
    return accounts.ClauderAccountProvider(
        run=_gate_run(scripted, calls=calls),
        sleep=(slept.append if slept is not None else (lambda _s: None)),
        should_stop=should_stop or (lambda: False),
    )


def limit_result():
    """A session the runtime itself classified as a usage limit (REQ-016's signal)."""
    return claude_mod.Result(claude_mod.Outcome.USAGE_LIMIT, "usage limit reached", [], 0)


def error_result():
    """The FlowSteward REQ-116 shape: a session death whose ending misses ``_LIMIT_MARKERS``,
    so the runtime classifies it ERROR — the ambiguity Decision 2 corroborates."""
    return claude_mod.Result(claude_mod.Outcome.ERROR, "", [{"type": "raw", "text": "boom"}], 1)


class ScriptedRunner:
    """A fake ``run_claude`` returning each scripted Result in turn (the last repeats),
    recording every command so the ``--repeat`` recovery signal is assertable."""

    def __init__(self, results):
        self._results = list(results)
        self.commands: list[str] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        result = self._results[min(len(self.commands) - 1, len(self._results) - 1)]
        return result


def _executor(project, accounts_provider, runner, *, steps=None, stop=None):
    steps = steps or [Step(id="REQ-080:develop", command="/advance REQ-080 develop",
                           req="REQ-080", verify=("true",))]
    return Executor(
        root=project,
        source=ListStepSource(steps),
        verifier=SimpleNamespace(verify=lambda step: (True, "green")),
        accounts=accounts_provider,
        runner=runner,
        committer=RecordingCommitter(),
        git=FakeGitTopology(current="dev"),
        stop=stop,
    )


def _events(project, name=None):
    path = project / ".devsteward" / "events.jsonl"
    evs = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    return [e for e in evs if name is None or e.get("event") == name]


# -- AC1: corroborate an ambiguous ERROR via the budget oracle ------------------


def test_error_corroborated_as_limit_is_requeued_not_failed(project, monkeypatch):
    """AC1 — the REQ-116 fingerprint. A session death that misses the limit markers
    (Outcome.ERROR) but whose *immediate* gate verdict is budget-exhausted is handled as a
    limit interruption: requeued (never FAILED), recorded as a corroborated ``usage_limit``
    and **not** ``step_failed``."""
    # gate calls: the step's precheck (proceed — there was budget when it started) → the
    # post-death corroboration probe (wait — the window closed under it).
    provider = _clauder(monkeypatch, [PROCEED, WAIT])
    ex = _executor(project, provider, ScriptedRunner([error_result()]))
    step = ex.steps()[0]

    res = ex.run_step(step)

    assert res.outcome is RunOutcome.LIMIT  # not FAILED — the stopping state REQ-116 hit
    led = Ledger(project)
    assert led.status_of(step.id) is not StepStatus.FAILED
    assert led.status_of(step.id) is StepStatus.RECOVER

    # The ledger tells the truth about *why*: a corroborated limit, not an opaque failure.
    assert not _events(project, "step_failed")
    limits = _events(project, "usage_limit")
    assert len(limits) == 1
    assert limits[0]["corroborated"] is True
    assert limits[0]["verdict"] == BudgetVerdict.EXHAUSTED.value
    assert "soonest-reset" in limits[0]["reason"]


def test_error_not_corroborated_stays_a_genuine_failure(project, monkeypatch):
    """AC1 (the other side) — the runtime signal stays primary. An ERROR while clauder says
    there *is* budget is a real code error: FAILED + ``step_failed``, exactly as before. A
    limit is corroborated, never assumed — otherwise every crash would be laundered into a
    retry and the engine would spin on genuine bugs."""
    provider = _clauder(monkeypatch, [PROCEED])
    ex = _executor(project, provider, ScriptedRunner([error_result()]))
    step = ex.steps()[0]

    res = ex.run_step(step)

    assert res.outcome is RunOutcome.FAILED
    assert Ledger(project).status_of(step.id) is StepStatus.FAILED
    assert len(_events(project, "step_failed")) == 1
    assert not _events(project, "usage_limit")


def test_unsatisfiable_verdict_also_corroborates(project, monkeypatch):
    """AC1 — "budget-exhausted" covers both exhausted verdicts: ``wait`` (75) and
    ``unsatisfiable`` (69). The latter still reclassifies the death honestly; it just does
    not resume (nothing to wait for), which AC5's stop list already covers."""
    provider = _clauder(monkeypatch, [PROCEED, UNSATISFIABLE])
    ex = _executor(project, provider, ScriptedRunner([error_result()]))

    res = ex.run_step(ex.steps()[0])

    assert res.outcome is RunOutcome.LIMIT
    assert _events(project, "usage_limit")[0]["corroborated"] is True


def test_corroboration_probe_never_waits(monkeypatch):
    """AC1 — the corroboration probe is a *read*: one gate call, no sleep, no re-gate, no
    admission. Waiting is ``precheck``'s job (Decision 3), reached by the run loop's next
    iteration — the probe must not grow a second copy of it."""
    calls: list = []
    slept: list = []
    provider = _clauder(monkeypatch, [WAIT, PROCEED], calls=calls, slept=slept)

    verdict, reason = provider.budget_verdict()

    assert verdict is BudgetVerdict.EXHAUSTED
    assert len(calls) == 1  # exactly one probe — it did not loop back for a second verdict
    assert slept == []  # and it never slept
    assert "wait" in reason


# -- AC2: the run does not stop; the existing gate waits and relaunches ---------


def test_rides_through_a_limit_waiting_at_the_gate(project, monkeypatch):
    """AC2 — the whole point. Session 1 dies on a limit; ``run`` does *not* stop. The loop
    re-enters the accounts precheck, which sleeps clauder's ``wait_seconds`` and re-gates,
    and the same step is relaunched once the gate opens — landing DONE."""
    slept: list = []
    # gate calls, in order: step-1 precheck (proceed) → post-death corroboration probe (wait)
    # → step-2 precheck: wait, sleep 3600, re-gate → proceed.
    provider = _clauder(
        monkeypatch, [PROCEED, WAIT, WAIT, PROCEED], slept=slept
    )
    runner = ScriptedRunner([limit_result(), ok_result()])
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=5)

    # The run rode through: two sessions, and the step finished rather than the run quitting.
    assert len(runner.commands) == 2
    assert [r.outcome for r in results] == [RunOutcome.LIMIT, RunOutcome.DONE]
    assert results[0].resumable is True
    assert Ledger(project).status_of("REQ-080:develop") is StepStatus.DONE
    # It waited out the window at the *existing* gate — clauder's duration, not a guess.
    assert sum(slept) == 3600


def test_rides_through_honors_a_clauder_account_switch(project, monkeypatch):
    """AC2 — an account switch performed by clauder during the re-gate is honored
    transparently. clauder owns the switch (REQ-058 Decision 3: no second switcher); the
    engine just re-prechecks and relaunches plain ``claude``."""
    provider = _clauder(monkeypatch, [PROCEED, WAIT, SWITCH])
    runner = ScriptedRunner([limit_result(), ok_result()])
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=5)

    assert [r.outcome for r in results] == [RunOutcome.LIMIT, RunOutcome.DONE]
    # The relaunch is plain `claude` — the switch happened inside clauder, not here.
    assert provider.claude_argv() == ["claude"]


def test_rides_through_a_limit_but_not_a_failure(project, monkeypatch):
    """AC2 — riding through a *limit* must not make the run ride through everything. A hard
    failure still stops so a human can look."""
    provider = _clauder(monkeypatch, [PROCEED])
    ex = _executor(project, provider, ScriptedRunner([error_result()]))

    results = ex.run(max_steps=5)

    assert [r.outcome for r in results] == [RunOutcome.FAILED]


# -- AC3: the relaunched session carries the recovery signal --------------------


def test_limit_requeues_recover_signal_so_relaunch_repeats(project, monkeypatch):
    """AC3 — a limit-interrupted step is requeued RECOVER (not PENDING), so its relaunch
    command carries ``--repeat`` and the resuming session assesses the killed attempt's
    partial edits instead of starting clean over a dirty tree. The manual workflow got this
    accidentally (``steward repeat`` sets RECOVER); the automatic resume does it on purpose."""
    provider = _clauder(monkeypatch, [PROCEED, WAIT, PROCEED])
    runner = ScriptedRunner([limit_result(), ok_result()])
    ex = _executor(project, provider, runner)

    ex.run(max_steps=5)

    assert "--repeat" not in runner.commands[0]  # the first attempt starts clean
    assert "--repeat" in runner.commands[1]  # the relaunch does not
    started = _events(project, "step_started")
    assert [e["recover"] for e in started] == [False, True]


def test_recover_signal_survives_the_interruption(project, monkeypatch):
    """AC3 — a step that was *already* RECOVER stays RECOVER through a limit death: the
    REQ-026 signal survives, so a resume-of-a-resume still repeats rather than silently
    reverting to a clean start."""
    led = Ledger(project)
    led.set_status("REQ-080:develop", StepStatus.RECOVER)
    led.save()

    provider = _clauder(monkeypatch, [PROCEED, WAIT, PROCEED])
    runner = ScriptedRunner([limit_result(), ok_result()])
    ex = _executor(project, provider, runner)

    ex.run(max_steps=5)

    assert all("--repeat" in c for c in runner.commands)
    assert len(runner.commands) == 2


# -- AC4: the consecutive-limit guard ------------------------------------------


def test_guard_stops_after_three_immediate_limits(project, monkeypatch):
    """AC4 — the tight-spin bound (Decision 5). clauder keeps saying "proceed" but sessions
    keep dying instantly (an account-state mismatch): after 3 limit deaths on the same step
    with no intervening gate wait and no progress, the run requeues the step and stops —
    today's behavior, rather than hammering the gate forever."""
    provider = _clauder(monkeypatch, [PROCEED])  # never waits: proceed every time
    runner = ScriptedRunner([limit_result()])  # and every session dies on a limit
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=20)

    assert len(results) == 3  # 3 strikes, then stop — not an unbounded spin
    assert [r.outcome for r in results] == [RunOutcome.LIMIT] * 3
    assert [r.resumable for r in results] == [True, True, False]
    # Requeued for a later run, and the guard says so in the ledger.
    assert Ledger(project).status_of("REQ-080:develop") is StepStatus.RECOVER
    guard = _events(project, "limit_guard")
    assert len(guard) == 1 and guard[0]["consecutive"] == 3


def test_gate_wait_resets_the_guard(project, monkeypatch):
    """AC4 — an intervening gate wait resets the counter: a run that genuinely waits out a
    window between limits is riding out a real budget cycle, not spinning, and must not be
    cut off at 3. Two deaths, a real wait, then two more → still running."""
    # Gate calls, two per attempt (precheck, then the post-death probe), except attempt 3
    # whose precheck WAITS and re-gates. The 5th call is that wait — it resets the streak.
    provider = _clauder(
        monkeypatch,
        [PROCEED, PROCEED, PROCEED, PROCEED, WAIT, PROCEED, PROCEED, PROCEED, PROCEED],
    )
    runner = ScriptedRunner([limit_result()])
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=4)

    # Four limit deaths without the guard tripping: the streak ran 1, 2, then the gate wait
    # cleared it, then 1, 2 again. Without the reset the 3rd death would have stopped the run
    # (as test_guard_stops_after_three_immediate_limits proves it does) and there would be
    # three results, not four — so this genuinely discriminates.
    assert len(results) == 4
    assert all(r.resumable for r in results)
    assert not _events(project, "limit_guard")
    assert provider.wait_count == 1  # exactly one real gate wait happened


def test_step_completion_resets_the_guard(project, monkeypatch):
    """AC4 — a completed step resets the counter. Progress anywhere means the engine is not
    wedged, so an earlier step's stale streak must not trip the guard later."""
    steps = [
        Step(id="REQ-080:develop", command="/advance REQ-080 develop",
             req="REQ-080", verify=("true",)),
        Step(id="REQ-081:develop", command="/advance REQ-081 develop",
             req="REQ-081", verify=("true",)),
    ]
    provider = _clauder(monkeypatch, [PROCEED])
    # REQ-080 limits twice, REQ-081 completes, REQ-080 limits twice more. With the
    # completion reset the streak never reaches 3, so nothing trips.
    ex = _executor(project, provider, ScriptedRunner([limit_result()]), steps=steps)

    ex.run(max_steps=2)  # two limit deaths on REQ-080 (lowest id first)
    assert ex._limit_streak == 2

    # A different step completing is progress — it clears the stale streak.
    ex.runner = ScriptedRunner([ok_result()])
    ex.run(only="REQ-081", max_steps=1)
    assert ex._limit_streak == 0
    assert Ledger(project).status_of("REQ-081:develop") is StepStatus.DONE


# -- AC5: degradation without the oracle ---------------------------------------


def test_no_clauder_on_path_stops_the_run_as_before(project, monkeypatch):
    """AC5 — auto-resume is a clauder-backed feature (Decision 6). With clauder absent from
    PATH there is no honest signal for when the budget clears, so a mid-run limit requeues
    the step and stops the run exactly as before this REQ. **No blind backoff loop.**"""
    slept: list = []
    provider = _clauder(monkeypatch, [PROCEED], slept=slept, present=False)
    assert not provider.available
    runner = ScriptedRunner([limit_result()])
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=5)

    assert [r.outcome for r in results] == [RunOutcome.LIMIT]
    assert results[0].resumable is False
    assert len(runner.commands) == 1  # it stopped — it did not relaunch
    assert slept == []  # and it never blind-polled
    assert _events(project, "usage_limit")[0]["verdict"] == BudgetVerdict.NO_ORACLE.value
    assert Ledger(project).status_of("REQ-080:develop") is StepStatus.RECOVER


def test_no_clauder_provider_without_the_oracle_seam(project):
    """AC5 — the oracle is an *optional* seam. A provider that does not implement
    ``budget_verdict`` at all (:class:`SingleAccountProvider`, or any consumer stand-in)
    reads as NO_ORACLE via the executor's fail-open getattr — it never rides out a limit and
    never raises for lacking the method."""
    provider = SingleAccountProvider()
    assert not hasattr(provider, "budget_verdict")
    runner = ScriptedRunner([limit_result()])
    ex = _executor(project, provider, runner)

    results = ex.run(max_steps=5)

    assert [r.outcome for r in results] == [RunOutcome.LIMIT]
    assert results[0].resumable is False
    assert len(runner.commands) == 1


def test_no_clauder_oracle_when_the_gate_call_fails(project, monkeypatch):
    """AC5 — "or the gate call failing". ``_gate`` degrades **open** so a flaky clauder never
    hard-fails a run (REQ-058 Decision 4) — but that fabricated ``proceed`` is the *absence*
    of an oracle, not a budget claim. Reading it as a real verdict would resume on a tool
    that cannot answer; the ``degraded`` marker keeps the two apart."""
    def explode(argv, **kwargs):
        raise OSError("clauder gate blew up")

    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/clauder")
    provider = accounts.ClauderAccountProvider(run=explode, sleep=lambda _s: None)

    # precheck still degrades open — a broken gate must not stop a healthy run...
    ok, _ = provider.precheck()
    assert ok is True
    # ...but the oracle honestly reports that it has nothing to say.
    verdict, _ = provider.budget_verdict()
    assert verdict is BudgetVerdict.NO_ORACLE

    runner = ScriptedRunner([limit_result()])
    results = _executor(project, provider, runner).run(max_steps=5)

    assert [r.outcome for r in results] == [RunOutcome.LIMIT]
    assert results[0].resumable is False
    assert len(runner.commands) == 1  # stopped as before this REQ


def test_no_clauder_error_still_fails_plainly(project, monkeypatch):
    """AC5 — without an oracle there is nothing to corroborate with, so an ERROR keeps its
    pre-REQ meaning: a plain FAILED. Absent clauder, the engine must not guess."""
    provider = _clauder(monkeypatch, [PROCEED], present=False)
    ex = _executor(project, provider, ScriptedRunner([error_result()]))

    res = ex.run_step(ex.steps()[0])

    assert res.outcome is RunOutcome.FAILED
    assert Ledger(project).status_of("REQ-080:develop") is StepStatus.FAILED


# -- AC6: the stop signal during a gate wait -----------------------------------


def test_stop_signal_during_gate_wait_ends_the_run_gracefully(project, monkeypatch):
    """AC6 — a stop (Ctrl-C) delivered while the run waits on the gate ends the run
    gracefully: no new session is launched and the interrupted step stays requeued for a
    later run. Riding out an hours-long window is only acceptable because the operator can
    always interrupt it."""
    flag = {"stop": False}
    # The stop lands during the *second* step's gate wait: the first precheck must pass.
    calls: list = []

    def should_stop():
        return flag["stop"]

    def stopping_sleep(_seconds):
        flag["stop"] = True  # the operator hits Ctrl-C mid-wait

    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/clauder")
    provider = accounts.ClauderAccountProvider(
        run=_gate_run([PROCEED, WAIT, WAIT, PROCEED], calls=calls),
        sleep=stopping_sleep,
        should_stop=should_stop,
    )
    runner = ScriptedRunner([limit_result(), ok_result()])
    ex = _executor(project, provider, runner,
                   stop=SimpleNamespace(should_stop=should_stop,
                                        register_child=lambda _p: None,
                                        clear_child=lambda: None))

    results = ex.run(max_steps=5)

    # Only the first session ever ran: the relaunch was abandoned in the gate wait.
    assert len(runner.commands) == 1
    assert results[-1].outcome is RunOutcome.LIMIT
    assert results[-1].resumable is False  # a stop is not a resumable limit
    # The step survives for a later run, with its recovery signal intact.
    assert Ledger(project).status_of("REQ-080:develop") is StepStatus.RECOVER
    assert any("stop" in (e.get("reason") or "") for e in _events(project, "quota_block"))

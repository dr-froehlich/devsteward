"""Engine-owned stamped-artifact drift: provenance lock, three-bucket detection, safe sync.

REQ-036 built this for the bundled skills; REQ-066 generalized the tracked set to all
engine-owned stamped artifacts (the skills **and** the root ``STEWARD.md`` manual) and
renamed the manifest ``skills.lock`` → ``stamped.lock`` (legacy read for back-compat) and the
verb ``sync-skills`` → ``sync`` (alias kept). The headless ACs run on synthetic stamped
projects in a temp dir; the drift machinery takes an injected ``templates_root`` so the
"template advanced" case is exercised without a second real install — we mutate a copy of the
bundled templates to stand in for an upgraded engine. The live FlowSteward closures (REQ-036
Finding 50, REQ-066 AC6) are the validate phase.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from devsteward import skillsync
from devsteward.cli import _package_templates, main
from devsteward.skillsync import Bucket, _bucket


def _stamp_project(tmp_path: Path) -> Path:
    target = tmp_path / "consumer"
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output
    return target


def _templates_copy(tmp_path: Path) -> Path:
    """A mutable copy of the bundled templates, standing in for the installed engine."""
    dst = tmp_path / "templates"
    shutil.copytree(_package_templates(), dst)
    return dst


# -- AC1 ----------------------------------------------------------------------


def test_new_seeds_lock_and_reports_in_sync(tmp_path, monkeypatch):
    """`steward new` writes a populated lock and every bundled skill reports in-sync."""
    target = _stamp_project(tmp_path)

    lock = skillsync.read_lock(target)
    names = skillsync.bundled_skill_names(_package_templates())
    assert names, "the installed template ships bundled skills"
    # REQ-066 generalized the lock to engine-owned stamped artifacts: every bundled skill is
    # recorded (plus STEWARD.md, asserted in test_new_seeds_stamped_lock_includes_manual...).
    assert set(names) <= set(lock), "every bundled skill is recorded in the lock"

    # Stamped copy byte-matches the template it was stamped from, so all in-sync.
    drift = skillsync.drift(target, _package_templates())
    assert drift == [], f"freshly stamped project should report no drift, got {drift}"

    # And `steward status` prints no drift section.
    monkeypatch.chdir(target)
    out = CliRunner().invoke(main, ["status"]).output
    assert "stamped artifacts" not in out


# -- AC2 ----------------------------------------------------------------------


def test_stale_skill_detected_then_synced(tmp_path, monkeypatch):
    """Template advances while the stamped copy is untouched → stale, then sync byte-matches."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)

    name = "advance"
    tpl = skillsync.template_skill_file(templates, name)
    tpl.write_text(tpl.read_text(encoding="utf-8") + "\n<!-- engine upgraded -->\n",
                   encoding="utf-8")

    drift = {d.name: d.bucket for d in skillsync.classify(target, templates)}
    assert drift[name] is Bucket.STALE
    assert all(b is Bucket.IN_SYNC for n, b in drift.items() if n != name)

    monkeypatch.chdir(target)
    status_before = CliRunner().invoke(main, ["status"]).output
    # REQ-066 Decision 3: the drift signal now points at the generalized `steward sync` verb.
    assert "steward sync" in status_before and "stale" in status_before

    res = CliRunner().invoke(main, ["sync-skills"])  # back-compat alias still works
    assert res.exit_code == 0, res.output
    assert "refreshed" in res.output

    stamped = skillsync.stamped_skill_file(target, name)
    assert stamped.read_bytes() == tpl.read_bytes(), "stamped now byte-matches the template"
    assert skillsync.drift(target, templates) == []
    assert skillsync.read_lock(target)[name] == skillsync._sha256(tpl)


# -- AC3 ----------------------------------------------------------------------


def test_customized_skill_not_clobbered_without_force(tmp_path, monkeypatch):
    """A locally-edited skill is customized (not stale); refused without --force, backed up with."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)

    name = "intake"
    stamped = skillsync.stamped_skill_file(target, name)
    edited = stamped.read_text(encoding="utf-8") + "\n<!-- local tweak -->\n"
    stamped.write_text(edited, encoding="utf-8")

    drift = {d.name: d.bucket for d in skillsync.classify(target, templates)}
    assert drift[name] is Bucket.CUSTOMIZED

    monkeypatch.chdir(target)
    res = CliRunner().invoke(main, ["sync-skills"])
    assert res.exit_code == 0, res.output
    assert "customized" in res.output and "--force" in res.output
    assert stamped.read_text(encoding="utf-8") == edited, "refused: not overwritten"

    forced = CliRunner().invoke(main, ["sync-skills", "--force"])
    assert forced.exit_code == 0, forced.output
    backup = stamped.with_name(stamped.name + skillsync.BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == edited, "local copy backed up to .orig"
    tpl = skillsync.template_skill_file(templates, name)
    assert stamped.read_bytes() == tpl.read_bytes(), "refreshed to template"
    assert skillsync.read_lock(target)[name] == skillsync._sha256(tpl)


# -- AC5 regression (Finding 50 live closure) ---------------------------------


def test_sync_backfills_full_lock_on_legacy_lockless_consumer(tmp_path, monkeypatch):
    """A pre-lock consumer: syncing the one drifted skill must still leave the lock
    fully populated, not a partial ``{drifted: ...}`` map.

    The live FlowSteward closure of AC5 caught this: on a consumer stamped before
    lock-seeding, ``sync-skills`` refreshed the one drifted skill but recorded a lock
    entry *only* for it, leaving the already-in-sync skills with no provenance — so they
    would later mis-bucket as ``customized`` the moment the template advanced. The lock
    must be a complete baseline (Decision 2/5).

    Note the lock-less reality: with no baseline a drifted skill can't be proven
    untouched, so it buckets ``customized`` (the conservative no-clobber bucket) and
    needs ``--force`` — the honest path on a legacy consumer.
    """
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)

    # Reproduce a legacy consumer: no provenance baseline at all.
    skillsync.lock_path(target).unlink()
    assert skillsync.read_lock(target) == {}

    # Exactly one skill has drifted (template advanced); the rest are untouched.
    drifted = "advance"
    tpl = skillsync.template_skill_file(templates, drifted)
    tpl.write_text(tpl.read_text(encoding="utf-8") + "\n<!-- engine upgraded -->\n",
                   encoding="utf-8")
    buckets = {d.name: d.bucket for d in skillsync.classify(target, templates)}
    assert buckets[drifted] is Bucket.CUSTOMIZED  # no lock baseline → conservative bucket

    monkeypatch.chdir(target)
    res = CliRunner().invoke(main, ["sync-skills", "--force"])
    assert res.exit_code == 0, res.output

    # The lock now records *every* bundled skill, not just the one that was refreshed
    # (REQ-066: plus the in-sync STEWARD.md it backfills — the full tracked set is baselined).
    lock = skillsync.read_lock(target)
    names = skillsync.bundled_skill_names(templates)
    assert set(names) <= set(lock), f"lock must be fully populated, got {sorted(lock)}"
    assert MANUAL in lock
    # Each entry is the truthful template hash; nothing reports drift afterwards.
    for name in names:
        assert lock[name] == skillsync._sha256(skillsync.template_skill_file(templates, name))
    assert skillsync.drift(target, templates) == []


# -- AC4 ----------------------------------------------------------------------


def test_drift_bucket_matrix():
    """The three-point classifier is correct across the full stamped/lock/template matrix."""
    A, B, C = "hashA", "hashB", "hashC"
    # (stamped, lock, template) -> bucket
    assert _bucket(A, A, A) is Bucket.IN_SYNC
    assert _bucket(A, A, B) is Bucket.STALE        # template moved only
    assert _bucket(B, A, A) is Bucket.CUSTOMIZED   # stamped edited only
    assert _bucket(C, A, B) is Bucket.BOTH_MOVED   # both diverged from lock
    assert _bucket(None, A, B) is Bucket.MISSING   # not stamped at all
    # A stamped copy that already matches the template is in-sync even with no lock baseline
    # (the lock-less fallback), and a no-lock copy that *differs* is the conservative bucket.
    assert _bucket(A, None, A) is Bucket.IN_SYNC
    assert _bucket(B, None, A) is Bucket.CUSTOMIZED


# =============================================================================
# REQ-066 — the tracked set generalizes to engine-owned stamped artifacts: the
# bundled skills *and* the root STEWARD.md manual. The mechanism is reused
# verbatim; these exercise the manual entering it (AC1–AC3), the lock rename's
# back-compat (AC4), and the onboard scaffold-stamp seeding (AC5). AC6 is the
# live FlowSteward closure (the validate phase).
# =============================================================================

MANUAL = skillsync.MANUAL_FILENAME


def _stamped_manual(root: Path) -> Path:
    return Path(root) / MANUAL


def _template_manual(templates_root: Path) -> Path:
    return Path(templates_root) / MANUAL


# -- AC1 ----------------------------------------------------------------------


def test_new_seeds_stamped_lock_includes_manual_in_sync(tmp_path, monkeypatch):
    """`steward new` stamps STEWARD.md, writes `.devsteward/stamped.lock` recording its
    template hash (and each skill's), and the fresh project reports every tracked artifact —
    STEWARD.md included — in-sync (no drift line)."""
    target = _stamp_project(tmp_path)

    # The manifest is the new stamped.lock (not a legacy skills.lock) and records STEWARD.md.
    assert skillsync.lock_path(target).is_file()
    assert not skillsync.legacy_lock_path(target).is_file()
    lock = skillsync.read_lock(target)
    assert MANUAL in lock, "STEWARD.md is baselined alongside the skills"
    assert set(skillsync.bundled_skill_names(_package_templates())) <= set(lock)

    # STEWARD.md is stamped at the consumer root and byte-matches the template it came from.
    stamped, template = _stamped_manual(target), _template_manual(_package_templates())
    assert stamped.is_file(), "the manual is stamped into the consumer root"
    assert stamped.read_bytes() == template.read_bytes()
    assert lock[MANUAL] == skillsync._sha256(template)

    # Every tracked artifact reports in-sync — no drift, no status section.
    assert skillsync.drift(target, _package_templates()) == []
    monkeypatch.chdir(target)
    out = CliRunner().invoke(main, ["status"]).output
    assert "stamped artifacts" not in out


# -- AC2 ----------------------------------------------------------------------


def test_missing_steward_manual_acquired_by_sync(tmp_path, monkeypatch):
    """A consumer lacking STEWARD.md (a project stamped before REQ-057) is surfaced (status
    reports it missing) and fixed (`steward sync` stamps it from the template) via the
    existing MISSING→refresh path — no new acquisition machinery."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)

    manual = _stamped_manual(target)
    manual.unlink()  # the pre-REQ-057 reality: the manual was never stamped

    buckets = {d.name: d.bucket for d in skillsync.classify(target, templates)}
    assert buckets[MANUAL] is Bucket.MISSING

    monkeypatch.chdir(target)
    status_before = CliRunner().invoke(main, ["status"]).output
    assert MANUAL in status_before and "missing" in status_before

    res = CliRunner().invoke(main, ["sync"])
    assert res.exit_code == 0, res.output

    template_manual = _template_manual(templates)
    assert manual.read_bytes() == template_manual.read_bytes(), "acquired, byte-matching template"
    assert skillsync.drift(target, templates) == []
    assert skillsync.read_lock(target)[MANUAL] == skillsync._sha256(template_manual)
    assert "stamped artifacts" not in CliRunner().invoke(main, ["status"]).output


# -- AC3 ----------------------------------------------------------------------


def test_steward_manual_stale_and_customized_buckets(tmp_path, monkeypatch):
    """STEWARD.md gets the same stale/customized handling as a skill: an advanced template
    with the stamped copy untouched is stale and refreshed; a consumer-edited manual is
    customized, refused without --force, and with --force backed up (.orig) then refreshed."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)
    monkeypatch.chdir(target)

    stamped, tpl = _stamped_manual(target), _template_manual(templates)

    # --- stale: template advances while the stamped copy is untouched ---
    tpl.write_text(tpl.read_text(encoding="utf-8") + "\n<!-- engine upgraded -->\n",
                   encoding="utf-8")
    buckets = {d.name: d.bucket for d in skillsync.classify(target, templates)}
    assert buckets[MANUAL] is Bucket.STALE
    assert all(b is Bucket.IN_SYNC for n, b in buckets.items() if n != MANUAL)

    res = CliRunner().invoke(main, ["sync"])
    assert res.exit_code == 0, res.output
    assert stamped.read_bytes() == tpl.read_bytes(), "stale manual refreshed to template"
    assert skillsync.drift(target, templates) == []

    # --- customized: the consumer edits its STEWARD.md ---
    edited = stamped.read_text(encoding="utf-8") + "\n<!-- local note -->\n"
    stamped.write_text(edited, encoding="utf-8")
    assert {d.name: d.bucket for d in skillsync.classify(target, templates)}[MANUAL] \
        is Bucket.CUSTOMIZED

    refused = CliRunner().invoke(main, ["sync"])
    assert refused.exit_code == 0, refused.output
    assert "customized" in refused.output and "--force" in refused.output
    assert stamped.read_text(encoding="utf-8") == edited, "refused: not overwritten"

    forced = CliRunner().invoke(main, ["sync", "--force"])
    assert forced.exit_code == 0, forced.output
    backup = stamped.with_name(stamped.name + skillsync.BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == edited, "local copy backed up to .orig"
    assert stamped.read_bytes() == tpl.read_bytes(), "refreshed to template under --force"
    assert skillsync.read_lock(target)[MANUAL] == skillsync._sha256(tpl)


# -- AC4 ----------------------------------------------------------------------


def test_legacy_skills_lock_read_and_migrated_and_alias(tmp_path, monkeypatch):
    """A project carrying only a legacy `.devsteward/skills.lock` has its provenance *read*
    (drift classified from it, not guessed), the next write migrates it to `stamped.lock`, and
    `steward sync-skills` still runs as an alias for `steward sync`."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    monkeypatch.setattr("devsteward.cli._package_templates", lambda: templates)

    # Reconstruct a pre-REQ-066 consumer: a skills-only legacy lock, no stamped.lock.
    legacy = {k: v for k, v in skillsync.read_lock(target).items() if k != MANUAL}
    skillsync.lock_path(target).unlink()
    skillsync.legacy_lock_path(target).write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert not skillsync.lock_path(target).is_file()

    # The legacy lock is *read*: advancing one skill's template leaves it STALE (provably
    # untouched against its recorded baseline). Without reading that baseline the bucket would
    # be the conservative CUSTOMIZED (no lock) — so STALE proves the legacy lock was consulted.
    name = "advance"
    tpl_skill = skillsync.template_skill_file(templates, name)
    tpl_skill.write_text(tpl_skill.read_text(encoding="utf-8") + "\n<!-- upgraded -->\n",
                         encoding="utf-8")
    assert {d.name: d.bucket for d in skillsync.classify(target, templates)}[name] is Bucket.STALE

    # The `sync-skills` alias still runs; the write migrates the manifest forward.
    monkeypatch.chdir(target)
    res = CliRunner().invoke(main, ["sync-skills"])
    assert res.exit_code == 0, res.output
    assert skillsync.lock_path(target).is_file(), "migrated forward to stamped.lock"
    assert not skillsync.legacy_lock_path(target).is_file(), "legacy skills.lock removed"
    assert skillsync.read_lock(target)[name] == skillsync._sha256(tpl_skill)


# -- AC5 ----------------------------------------------------------------------


def test_onboard_sync_seeds_full_lock_and_preserves_existing(tmp_path):
    """The onboard scaffold-stamp step (`steward sync`) on a post-convert state — a
    `.devsteward/` ledger present, but no stamped engine-owned artifacts and no lock — stamps
    the full engine-owned set including STEWARD.md, writes a populated `stamped.lock`, and
    leaves a pre-existing same-named project artifact untouched (merge, never overwrite)."""
    templates = _templates_copy(tmp_path)

    # The onboard target: a ledger dir, no stamped artifacts, no lock.
    target = tmp_path / "onboard_target"
    (target / ".devsteward").mkdir(parents=True)
    assert skillsync.read_lock(target) == {}

    # The project already owns a same-named skill with its own content (a real collision).
    owned = "intake"
    owned_file = skillsync.stamped_skill_file(target, owned)
    owned_file.parent.mkdir(parents=True, exist_ok=True)
    owned_text = "# the project's own intake skill — keep me\n"
    owned_file.write_text(owned_text, encoding="utf-8")

    res = skillsync.sync(target, templates)  # the onboard scaffold-stamp step

    # STEWARD.md is acquired, byte-matches the template, and is baselined in stamped.lock.
    assert _stamped_manual(target).read_bytes() == _template_manual(templates).read_bytes()
    assert skillsync.lock_path(target).is_file()
    lock = skillsync.read_lock(target)
    assert MANUAL in lock

    # Every engine-owned artifact *except the pre-existing collision* is stamped and baselined.
    expected = {MANUAL}
    for name in skillsync.bundled_skill_names(templates):
        if name == owned:
            continue
        assert skillsync.stamped_skill_file(target, name).is_file(), f"{name} stamped"
        expected.add(name)
    assert expected <= set(lock), "the lock baselines the full stamped set"

    # The pre-existing artifact is preserved untouched, reported customized, not baselined.
    assert owned_file.read_text(encoding="utf-8") == owned_text, "merge, never overwrite"
    assert owned in res.refused
    assert owned not in lock, "a refused customized artifact is not falsely baselined"

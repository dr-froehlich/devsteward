"""REQ-036 — bundled-skill drift: provenance lock, three-bucket detection, safe sync.

AC1–AC4 run headless on synthetic stamped projects in a temp dir. AC5 is the manual
FlowSteward closure of Finding 50 (the validate phase). The drift machinery takes an
injected ``templates_root`` so the "template advanced" case is exercised without a second
real install — we mutate a copy of the bundled templates to stand in for an upgraded engine.
"""

from __future__ import annotations

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
    assert set(lock) == set(names), "every bundled skill is recorded in the lock"

    # Stamped copy byte-matches the template it was stamped from, so all in-sync.
    drift = skillsync.drift(target, _package_templates())
    assert drift == [], f"freshly stamped project should report no drift, got {drift}"

    # And `steward status` prints no drift section.
    monkeypatch.chdir(target)
    out = CliRunner().invoke(main, ["status"]).output
    assert "sync-skills" not in out


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
    assert "sync-skills" in status_before and "stale" in status_before

    res = CliRunner().invoke(main, ["sync-skills"])
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

    # The lock now records *every* bundled skill, not just the one that was refreshed.
    lock = skillsync.read_lock(target)
    names = skillsync.bundled_skill_names(templates)
    assert set(lock) == set(names), f"lock must be fully populated, got {sorted(lock)}"
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

"""REQ-083 AC2 — the ``roadmap_file`` config seam is gone, and a legacy key is inert.

The property had zero readers in the engine, so removing it costs nothing. What must not
break is a consumer whose ``config.yaml`` still carries the key: ``load_config`` reads
known keys via ``data.get(...)``, so an unknown key parses fine and is simply never read
(REQ-083 decision 2) — no warning, no migration verb. This pins that tolerance is
structural rather than incidental.
"""

from __future__ import annotations

import dataclasses

from devsteward.config import Config, load_config

LEGACY_CONFIG = """\
profile: req
requirements_dir: docs/requirements
index_file: docs/requirements/REQUIREMENTS_INDEX.md
roadmap_file: docs/requirements/ROADMAP.md
claude:
  permission_mode: dangerously-skip
"""


def test_config_exposes_no_roadmap_seam():
    field_names = {f.name for f in dataclasses.fields(Config)}
    assert "roadmap_file" not in field_names
    assert not hasattr(Config, "roadmap_path")


def test_legacy_roadmap_key_loads_and_is_ignored(tmp_path):
    ledger = tmp_path / ".devsteward"
    ledger.mkdir()
    (ledger / "config.yaml").write_text(LEGACY_CONFIG, encoding="utf-8")

    cfg = load_config(tmp_path)

    # The stale key never becomes a field or a path...
    assert not hasattr(cfg, "roadmap_file")
    assert not hasattr(cfg, "roadmap_path")
    # ...it survives only as unread raw data, and the real keys still load.
    assert cfg.raw["roadmap_file"] == "docs/requirements/ROADMAP.md"
    assert cfg.index_file == "docs/requirements/REQUIREMENTS_INDEX.md"

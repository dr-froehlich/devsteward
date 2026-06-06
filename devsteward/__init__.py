"""DevSteward — a controlled baseline + automation engine for Claude Code projects.

The package ships two things in one wheel (the material-core pattern):

* the **engine** (``devsteward.core`` + ``devsteward.profiles``), exposed as the
  ``steward`` CLI, and
* the bundled **scaffolding** (``devsteward/templates``) that ``steward new``
  stamps into a new, private consumer project.

See ``devsteward/handbook/`` for the reference guide.
"""

__version__ = "0.1.0"

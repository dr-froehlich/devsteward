"""The status dashboard (REQ-097): one local browser page over every stamped project.

Two halves, split on purpose:

* :mod:`devsteward.dashboard.model` — pure reads. Discovers projects under a root, derives
  each one's status the way ``steward status`` does, reads git facts read-only, joins the
  backlog standings, and aggregates what waits on the operator. No web framework here; the
  CLI and the tests use it directly.
* :mod:`devsteward.dashboard.app` — the Flask application (the optional ``dashboard``
  extra): routes that render the model and form handlers that call the **same** verb
  functions the CLI calls (:mod:`devsteward.verbs`, :mod:`devsteward.profiles.req.backlog`).
  It never spawns a Claude session and never runs a batch verb (Decision 5).
"""

#: The install hint ``steward dashboard`` prints when the extra is missing (Decision 3).
INSTALL_HINT = (
    "the dashboard needs the `dashboard` extra (flask, markdown): from the devsteward "
    "checkout run `pipx install --editable '.[dashboard]' --force`, or add it to an "
    "existing install with `pipx inject devsteward flask markdown`."
)

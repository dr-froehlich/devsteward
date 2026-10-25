"""The REQ-workflow profile — the only content-aware layer.

Derives Design → Build → Land steps from the REQ files and sequences whole
requirements in dependency order, while letting independent requirements interleave.
"""

from .reqfile import ReqFile, load_reqs, parse_req
from .source import ReqStepSource

__all__ = ["ReqFile", "load_reqs", "parse_req", "ReqStepSource"]

import sys
from pathlib import Path

# Package root (backend/backend) for application.* imports when cwd varies.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Repo root (naturepath-backend) so tests can import scripts.* helpers.
_REPO_ROOT = _ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

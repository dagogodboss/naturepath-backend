#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_REPO_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/../frontend"
BACKEND_LOG="$ROOT_DIR/.backend-dev.log"
FRONTEND_LOG="$ROOT_DIR/.frontend-dev.log"

cleanup() {
  echo
  echo "Stopping local services..."
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

require_cmd() {
  local cmd="$1"
  local brew_pkg="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd"
    echo "Install it with: brew install $brew_pkg"
    exit 1
  fi
}

require_cmd "python3" "python"
require_cmd "node" "node"
require_cmd "npm" "node"

if [[ -f "$BACKEND_DIR/.env" ]]; then
  while IFS= read -r raw_line; do
    line="$(echo "$raw_line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" ]] && continue
    [[ "$line" == \#* ]] && continue
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      key="${line%%=*}"
      value="${line#*=}"
      if [[ -z "${!key:-}" ]]; then
        export "$key=$value"
      fi
    fi
  done < "$BACKEND_DIR/.env"
fi

MONGO_URL="${MONGO_URL:-${MONGODB_URL:-${MONGO_URI:-}}}"
if [[ -n "${MONGO_URL}" ]]; then
  MONGO_URL="${MONGO_URL/\/\?/\?}"
fi
DB_NAME="${DB_NAME:-natural_path_spa}"
MONGO_HOST_LOCAL="${MONGO_HOST_LOCAL:-127.0.0.1}"
MONGO_PORT="${MONGO_PORT:-27017}"
if [[ -z "${MONGO_URL}" ]]; then
  MONGO_URL="mongodb://${MONGO_HOST_LOCAL}:${MONGO_PORT}/${DB_NAME}"
fi

echo "Preparing backend environment..."
cd "$BACKEND_DIR"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -U pip >/dev/null
python -m pip install -r requirements.txt >/dev/null

echo "Checking seeded service catalog..."
seed_check_output="$(
python - <<'PY'
import os
import sys
from pymongo import MongoClient

mongo_url = os.environ.get("MONGO_URL")
db_name = os.environ.get("DB_NAME", "natural_path_spa")
client = MongoClient(mongo_url)
db = client[db_name]

services_count = db.services.count_documents({})
benefits_count = db.services.count_documents({"benefits.0": {"$exists": True}})
discovery_count = db.services.count_documents({"is_discovery_entry": True})
reviews_count = db.service_reviews.count_documents({})

print(
    f"services={services_count} "
    f"with_benefits={benefits_count} "
    f"discovery_entries={discovery_count} "
    f"reviews={reviews_count}"
)

if services_count == 0 or benefits_count == 0 or discovery_count == 0:
    sys.exit(7)
PY
)" || seed_check_status=$?
seed_check_status="${seed_check_status:-0}"
if [[ "$seed_check_status" -eq 7 ]]; then
  echo "Seed data missing or incomplete. Running scripts/seed_services.py ..."
  (
    cd "$BACKEND_REPO_DIR"
    PYTHONPATH=. MONGO_URL="$MONGO_URL" python3 scripts/seed_services.py
  )
  echo "Seed complete."
  seed_check_output="$(
python - <<'PY'
import os
from pymongo import MongoClient

mongo_url = os.environ.get("MONGO_URL")
db_name = os.environ.get("DB_NAME", "natural_path_spa")
client = MongoClient(mongo_url)
db = client[db_name]
print(
    f"services={db.services.count_documents({})} "
    f"with_benefits={db.services.count_documents({'benefits.0': {'$exists': True}})} "
    f"discovery_entries={db.services.count_documents({'is_discovery_entry': True})} "
    f"reviews={db.service_reviews.count_documents({})}"
)
PY
)"
fi
if [[ "$seed_check_status" -ne 0 && "$seed_check_status" -ne 7 ]]; then
  echo "WARNING: Could not verify service/review seed status (Mongo may be unreachable)."
fi
echo "Seed status: $seed_check_output"

echo "Checking owner/admin account..."
owner_check_output="$(
python - <<'PY'
import os
import sys
from pymongo import MongoClient

mongo_url = os.environ.get("MONGO_URL")
db_name = os.environ.get("DB_NAME", "natural_path_spa")
client = MongoClient(mongo_url)
db = client[db_name]

admin_count = db.users.count_documents({"role": "admin", "is_active": True})
owner_count = db.users.count_documents(
    {
        "email": {"$in": ["admin@thenaturalpath.com", "Nmoore@thenaturalpathla.com"]},
        "is_active": True,
    }
)
print(f"active_admins={admin_count} active_owner_candidates={owner_count}")
if admin_count == 0 and owner_count == 0:
    sys.exit(9)
PY
)" || owner_check_status=$?
owner_check_status="${owner_check_status:-0}"
if [[ "$owner_check_status" -eq 9 ]]; then
  if [[ -n "${OWNER_PASSWORD:-}" ]]; then
    echo "No active admin/owner account found. Running scripts/seed_owner.py ..."
    (
      cd "$BACKEND_REPO_DIR"
      PYTHONPATH=. MONGO_URL="$MONGO_URL" OWNER_PASSWORD="$OWNER_PASSWORD" python3 scripts/seed_owner.py
    )
    owner_check_output="$(
python - <<'PY'
import os
from pymongo import MongoClient

mongo_url = os.environ.get("MONGO_URL")
db_name = os.environ.get("DB_NAME", "natural_path_spa")
client = MongoClient(mongo_url)
db = client[db_name]
admin_count = db.users.count_documents({"role": "admin", "is_active": True})
owner_count = db.users.count_documents(
    {"email": {"$in": ["admin@thenaturalpath.com", "Nmoore@thenaturalpathla.com"]}, "is_active": True}
)
print(f"active_admins={admin_count} active_owner_candidates={owner_count}")
PY
)"
  else
    echo "WARNING: No active admin/owner account found."
    echo "Set OWNER_PASSWORD in your environment to auto-seed owner via scripts/seed_owner.py."
  fi
fi
if [[ "$owner_check_status" -ne 0 && "$owner_check_status" -ne 9 ]]; then
  echo "WARNING: Could not verify owner/admin status (Mongo may be unreachable)."
fi
echo "Owner/admin status: $owner_check_output"

echo "Preparing frontend environment..."
cd "$FRONTEND_DIR"
if [[ ! -d "node_modules" ]]; then
  npm install
fi

echo "Starting backend on http://localhost:8001 ..."
cd "$BACKEND_DIR"
MONGO_URL="$MONGO_URL" uvicorn server:app --host 0.0.0.0 --port 8001 >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173 ..."
cd "$FRONTEND_DIR"
npm run dev -- --host 0.0.0.0 --port 5173 >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 2

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend failed to start. Check $BACKEND_LOG"
  exit 1
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "Frontend failed to start. Check $FRONTEND_LOG"
  exit 1
fi

echo
echo "Services are running:"
echo "  Backend : http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo
echo "Logs:"
echo "  $BACKEND_LOG"
echo "  $FRONTEND_LOG"
echo
echo "Press Ctrl+C to stop both."

wait "$BACKEND_PID" "$FRONTEND_PID"

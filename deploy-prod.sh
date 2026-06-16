#!/usr/bin/env bash
# ══════════════════════════════════════════════════
# Bob Manager — Production Deployment Script
# Run after: git pull origin main
# Usage:    ./deploy-prod.sh [--skip-migrations] [--no-sandbox]
# ══════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}▶${NC} $1"; }
ok()   { echo -e "${GREEN}✔${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✖${NC} $1" >&2; }

SKIP_MIGRATIONS=false
NO_SANDBOX=false

for arg in "$@"; do
  case "$arg" in
    --skip-migrations) SKIP_MIGRATIONS=true ;;
    --no-sandbox)      NO_SANDBOX=true ;;
    -h|--help)
      echo "Usage: $0 [--skip-migrations] [--no-sandbox]"
      echo "  --skip-migrations  Skip database migration step"
      echo "  --no-sandbox       Skip sandbox image build"
      exit 0 ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

cd "$(dirname "$0")"
COMPOSE="docker compose"

# ── Pre-flight checks ────────────────────────────
log "Pre-flight checks..."

if [ ! -f .env ]; then
  err ".env file not found. Copy .env.example and configure it first."
  exit 1
fi

if ! docker info &>/dev/null; then
  err "Docker is not running."
  exit 1
fi

ok "Pre-flight passed"

# ── Step 1: Stop services ────────────────────────
log "Stopping services..."
$COMPOSE stop bob-api bob-ui bob-remotion 2>/dev/null || true
ok "Application services stopped (DB stays up for migrations)"

# ── Step 2: Build updated images ─────────────────
log "Building images..."
$COMPOSE build --parallel bob-api bob-ui bob-remotion
ok "Application images built"

if [ "$NO_SANDBOX" = false ]; then
  log "Building sandbox image..."
  $COMPOSE build bob-sandbox
  ok "Sandbox image built"
else
  warn "Sandbox build skipped (--no-sandbox)"
fi

# ── Step 2.5: Ensure volume ownership matches container UID 1000 ──
# CSO #3 made bob-api + bob-sandbox run as UID 1000. Docker volumes
# that were ever written by a pre-CSO #3 (root) container keep root
# ownership, which causes Errno 13 on every lab/agent Run. Idempotent:
# chown is a no-op when ownership already matches. Pinned alpine for
# reproducibility.
log "Ensuring volume ownership (CSO #3 — UID 1000)..."
docker run --rm \
    -v bob-manager_lab_resources:/lab_resources \
    -v bob-manager_qdrant_staging:/qdrant_staging \
    alpine:3.20 \
    sh -c "chown -R 1000:1000 /lab_resources /qdrant_staging"
ok "Volume ownership ensured (uid 1000)"

# ── Step 3: Database migrations ──────────────────
if [ "$SKIP_MIGRATIONS" = false ]; then
  log "Ensuring database is running..."
  $COMPOSE up -d bob-db
  # Wait for healthy
  for i in $(seq 1 30); do
    if $COMPOSE exec -T bob-db pg_isready -U "${POSTGRES_USER:-bobmanager}" &>/dev/null; then
      break
    fi
    sleep 1
  done

  if ! $COMPOSE exec -T bob-db pg_isready -U "${POSTGRES_USER:-bobmanager}" &>/dev/null; then
    err "Database did not become ready in 30s"
    exit 1
  fi
  ok "Database is ready"

  log "Applying migrations..."
  MIGRATION_DIR="control-plane/app/migrations"
  APPLIED=0
  SKIPPED=0

  # Apply numbered migrations in order (002-999)
  for f in $(ls "$MIGRATION_DIR"/0*.sql 2>/dev/null | sort); do
    BASENAME=$(basename "$f")
    # Each migration uses IF NOT EXISTS / IF NOT EXISTS, so safe to re-run
    if $COMPOSE exec -T bob-db psql -U "${POSTGRES_USER:-bobmanager}" -d "${POSTGRES_DB:-bobmanager}" -f "/dev/stdin" < "$f" &>/dev/null; then
      APPLIED=$((APPLIED + 1))
    else
      warn "Migration $BASENAME had warnings (may be OK if already applied)"
      SKIPPED=$((SKIPPED + 1))
    fi
  done

  ok "Migrations done: $APPLIED applied, $SKIPPED with warnings"
else
  warn "Migrations skipped (--skip-migrations)"
fi

# ── Step 4: Recreate services ────────────────────
log "Starting services with new images..."
$COMPOSE up -d --force-recreate bob-api bob-ui bob-remotion
ok "Application services started"

# ── Step 5: Health check ─────────────────────────
log "Waiting for API health..."
API_PORT=$(grep -oP 'API_PORT=\K[0-9]+' .env 2>/dev/null || echo "8888")
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${API_PORT}/api/v1/public/health" &>/dev/null; then
    ok "API is healthy"
    break
  fi
  sleep 2
done

if ! curl -sf "http://localhost:${API_PORT}/api/v1/public/health" &>/dev/null; then
  warn "API health check failed — check logs: docker compose logs bob-api"
fi

# ── Step 6: Verify all containers ────────────────
log "Container status:"
$COMPOSE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
  || $COMPOSE ps

echo ""
ok "Deployment complete!"
echo ""
echo -e "  ${CYAN}Useful commands:${NC}"
echo "    docker compose logs -f bob-api     # API logs"
echo "    docker compose logs -f bob-ui      # Frontend logs"
echo "    docker compose restart bob-api     # Restart API"
echo ""

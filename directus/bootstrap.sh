#!/bin/sh
# Wait for Directus to be ready, then apply schema snapshot

set -e

DIRECTUS_URL="${DIRECTUS_URL:-http://directus:8055}"
DIRECTUS_TOKEN="${DIRECTUS_TOKEN:-admin-token-change-me}"
MAX_WAIT=120
WAITED=0

echo "Waiting for Directus to be ready..."
until curl -sf "${DIRECTUS_URL}/server/health" > /dev/null 2>&1; do
  sleep 3
  WAITED=$((WAITED + 3))
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "Directus did not start in time"
    exit 1
  fi
done

echo "Directus is ready. Applying schema snapshot..."
curl -sf -X POST \
  -H "Authorization: Bearer ${DIRECTUS_TOKEN}" \
  -H "Content-Type: application/json" \
  "${DIRECTUS_URL}/schema/apply?force=true" \
  -d @/snapshot/schema.yaml \
  || echo "Schema apply returned non-zero (may already be applied)"

echo "Schema bootstrap done."

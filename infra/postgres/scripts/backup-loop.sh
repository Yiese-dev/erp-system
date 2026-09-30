#!/bin/bash
# Automated physical base backups; together with continuous WAL archiving these enable point-in-time recovery.
set -uo pipefail
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
KEEP="${BACKUP_KEEP:-7}"
BASE_DIR=/backups/base
mkdir -p "$BASE_DIR"

log() { printf '{"service":"backup","level":"%s","event":"%s","detail":"%s","at":"%s"}\n' "$1" "$2" "$3" "$(date -u +%FT%TZ)"; }

until pg_isready -h "${PGHOST:-postgres}" -U replicator -q; do sleep 2; done

take_backup() {
  local stamp target started
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="${BASE_DIR}/${stamp}"
  started=$(date +%s)
  if pg_basebackup -h "${PGHOST:-postgres}" -U replicator -D "${target}.partial" -Ft -z -X fetch --checkpoint=fast -l "campus-${stamp}"; then
    mv "${target}.partial" "$target"
    echo "{\"completed_at\":\"$(date -u +%FT%TZ)\",\"backup\":\"${stamp}\",\"seconds\":$(( $(date +%s) - started )),\"bytes\":$(du -sb "$target" | cut -f1)}" > /backups/last_success.json
    log info backup_completed "$stamp"
    ls -1d "${BASE_DIR}"/2* 2>/dev/null | sort | head -n -"${KEEP}" | xargs -r rm -rf
  else
    rm -rf "${target}.partial"
    log error backup_failed "$stamp"
  fi
}

while true; do
  latest="$(ls -1d "${BASE_DIR}"/2* 2>/dev/null | sort | tail -n 1)"
  age=$INTERVAL
  if [ -n "$latest" ]; then age=$(( $(date +%s) - $(stat -c %Y "$latest") )); fi
  if [ "$age" -ge "$INTERVAL" ]; then take_backup; fi
  sleep 60
done

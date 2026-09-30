#!/bin/bash
# Hot standby: clone the primary with a streaming base backup, then follow it read-only.
set -euo pipefail
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  until pg_basebackup -h "${PRIMARY_HOST:-postgres}" -U replicator -D "$PGDATA" -R -X stream --checkpoint=fast; do
    echo "waiting for primary..."; sleep 3
  done
  chmod 700 "$PGDATA"
fi
exec postgres -c hot_standby=on -c archive_mode=off

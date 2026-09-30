#!/bin/bash
# PostgreSQL archive_command: copy a completed WAL segment to the archive atomically, never overwriting a different file.
set -euo pipefail
source_path="$1"
name="$2"
target="/wal-archive/${name}"
if [ -f "$target" ]; then
  cmp -s "$source_path" "$target" && exit 0
  echo "archive-wal: ${name} already archived with different content" >&2
  exit 1
fi
cp "$source_path" "${target}.partial"
sync "${target}.partial" 2>/dev/null || true
mv "${target}.partial" "$target"

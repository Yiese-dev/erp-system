#!/bin/bash
# Point-in-time recovery drill. Restores the newest base backup taken before TARGET into an ISOLATED
# temporary cluster (port 5499 inside this container), replays archived WAL up to TARGET, verifies
# every service database, then shuts the copy down. The live database is never touched.
#
# Usage: docker compose run --rm backup pitr-drill.sh "2026-09-30 14:05:00+01"
set -euo pipefail
TARGET="${1:?usage: pitr-drill.sh 'YYYY-MM-DD HH:MM:SS+01'}"
WORK=/tmp/pitr-restore
PORT=5499
target_epoch=$(date -d "$TARGET" +%s)

base=""
for candidate in $(ls -1d /backups/base/2* 2>/dev/null | sort -r); do
  stamp=$(basename "$candidate")
  started=$(date -d "${stamp:0:4}-${stamp:4:2}-${stamp:6:2} ${stamp:9:2}:${stamp:11:2}:${stamp:13:2} UTC" +%s)
  if [ "$started" -lt "$target_epoch" ]; then base="$candidate"; break; fi
done
[ -n "$base" ] || { echo "No base backup older than ${TARGET}. Take one first (it runs automatically at start-up)."; exit 1; }

echo "== Restoring base backup $(basename "$base") and replaying WAL to ${TARGET}"
clock_start=$(date +%s)
rm -rf "$WORK" && mkdir -p "$WORK" && chmod 700 "$WORK"
tar -xzf "$base/base.tar.gz" -C "$WORK"
cat >> "$WORK/postgresql.auto.conf" <<EOF
restore_command = 'cp /wal-archive/%f "%p"'
recovery_target_time = '${TARGET}'
recovery_target_action = 'promote'
archive_mode = off
EOF
touch "$WORK/recovery.signal"
pg_ctl -D "$WORK" -l /tmp/pitr.log -w -t 900 -o "-p ${PORT} -c listen_addresses='' -c unix_socket_directories=/tmp -c archive_mode=off" start
until [ "$(psql -h /tmp -p "$PORT" -U postgres -Atc 'select not pg_is_in_recovery()' 2>/dev/null)" = "t" ]; do sleep 1; done
elapsed=$(( $(date +%s) - clock_start ))

q() { psql -h /tmp -p "$PORT" -U postgres -d "$1" -Atc "$2"; }
echo "== Recovered in ${elapsed}s (RTO measured for this drill)"
echo "identity_db : users=$(q identity_db 'select count(*) from users') sessions=$(q identity_db 'select count(*) from sessions')"
echo "academic_db : registrations=$(q academic_db 'select count(*) from registrations') results=$(q academic_db 'select count(*) from results') latest_registration=$(q academic_db 'select max(created_at) from registrations')"
echo "finance_db  : invoices=$(q finance_db 'select count(*) from invoices') payments=$(q finance_db 'select count(*) from payments') expenses=$(q finance_db 'select count(*) from expenses') latest_payment=$(q finance_db 'select max(paid_at) from payments')"
echo "finance_db  : ledger_balanced=$(q finance_db 'select coalesce(sum(debit),0) = coalesce(sum(credit),0) from journal_lines') paid_matches_payments=$(q finance_db 'select bool_and(i.paid = coalesce(p.total,0)) from invoices i left join (select invoice_id, sum(amount) total from payments group by invoice_id) p on p.invoice_id = i.id')"
echo "hr_db       : employees=$(q hr_db 'select count(*) from employees') leave_requests=$(q hr_db 'select count(*) from leave_requests') payslips=$(q hr_db 'select count(*) from payslips')"
echo "== Recovery point reached: $(q postgres 'select pg_last_xact_replay_timestamp()')"
pg_ctl -D "$WORK" -m fast -w stop >/dev/null
rm -rf "$WORK"
echo "== Drill complete. The restored copy was discarded; production data was not modified."

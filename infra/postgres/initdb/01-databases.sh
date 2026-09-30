#!/bin/bash
# Database-per-service on one server: each service gets its own database, an owner role (migrations only)
# and a runtime role that cannot bypass row-level security or reach any other service's database.
set -euo pipefail

for service in identity academic finance hr; do
  upper="${service^^}"
  owner_var="${upper}_OWNER_PASSWORD"
  app_var="${upper}_APP_PASSWORD"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v owner="${service}_owner" -v app="${service}_app" -v db="${service}_db" \
    -v owner_password="${!owner_var:?${owner_var} is required}" -v app_password="${!app_var:?${app_var} is required}" <<'SQL'
CREATE ROLE :"owner" LOGIN PASSWORD :'owner_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE :"app" LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 120;
CREATE DATABASE :"db" OWNER :"owner";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"owner", :"app";
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${service}_db" \
    -v owner="${service}_owner" -v app="${service}_app" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
SQL
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v replication_password="${REPLICATION_PASSWORD:?REPLICATION_PASSWORD is required}" <<'SQL'
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD :'replication_password';
SQL

echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
echo "Campus ERP databases and roles created"

#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"

usage() {
    printf 'Usage: bash update.sh [--no-pull]\n'
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

pull_latest=1
case "${1:-}" in
    "") ;;
    --no-pull) pull_latest=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { usage >&2; exit 2; }

for command in docker git curl openssl flock jq; do
    command -v "$command" >/dev/null || fail "Install $command first; see README.md."
done
docker compose version >/dev/null || fail "Install the Docker Compose v2 plugin."
docker info >/dev/null 2>&1 || fail "Docker is not running or this user cannot access it."

git_dir=$(git rev-parse --absolute-git-dir)
exec 9>"$git_dir/campus-deploy.lock"
flock -n 9 || fail "Another deployment is already running."

if (( pull_latest )); then
    [[ -z $(git status --porcelain --untracked-files=normal) ]] || fail "The checkout has local changes. Commit or move them, or use --no-pull to deploy as-is."
    upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}') || fail "Set an upstream branch or use --no-pull."
    git fetch --prune
    git merge-base --is-ancestor HEAD "$upstream" || fail "The checkout has local commits or diverges from its upstream. Resolve this before deploying."
    git merge --ff-only "$upstream"
    exec bash ./update.sh --no-pull 9>&-
fi

compose=(docker compose --project-name campus-erp --env-file .env -f docker-compose.yml)

if [[ ! -e .env ]]; then
    [[ -z $(docker volume ls --filter label=com.docker.compose.project=campus-erp --format '{{.Name}}') ]] || fail "Existing Campus volumes found without .env. Restore the original .env; do not generate replacement database passwords."
    env_tmp=$(mktemp .env.XXXXXX)
    trap 'rm -f -- "$env_tmp"' EXIT
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}
        case "$line" in
            CAMPUS_DEMO=*) line='CAMPUS_DEMO=1' ;;
            CAMPUS_ORIGINS=*) line='CAMPUS_ORIGINS=https://campus--erp.duckdns.org' ;;
            *=*)
                key=${line%%=*}
                case "$key" in
                    *_PASSWORD|WEBHOOK_SECRET|QR_SECRET|SIMULATOR_KEY)
                        line="$key=$(openssl rand -hex 32)"
                        ;;
                esac
                ;;
        esac
        printf '%s\n' "$line" >>"$env_tmp"
    done <.env.example
    mv -- "$env_tmp" .env
    trap - EXIT
    printf 'Created private .env with random secrets and a private demo login password.\n'
fi
chmod 600 .env

"${compose[@]}" config --quiet
"${compose[@]}" config --format json | jq --exit-status --raw-output '
    ([.services[].environment // {}] | add) as $env |
    ["POSTGRES_PASSWORD", "REPLICATION_PASSWORD", "IDENTITY_OWNER_PASSWORD", "IDENTITY_APP_PASSWORD",
     "ACADEMIC_OWNER_PASSWORD", "ACADEMIC_APP_PASSWORD", "FINANCE_OWNER_PASSWORD", "FINANCE_APP_PASSWORD",
     "HR_OWNER_PASSWORD", "HR_APP_PASSWORD", "RABBITMQ_DEFAULT_PASS", "GF_SECURITY_ADMIN_PASSWORD",
     "WEBHOOK_SECRET", "QR_SECRET", "SIMULATOR_KEY", "CAMPUS_DEMO_PASSWORD"] as $required |
    [$required[] | . as $name | ($env[$name] // "" | tostring) as $value |
     select($value == "" or ($value | startswith("change-me-"))
            or $value == "local-development-only-secret" or $value == "CampusDemo!2026") | $name] as $bad |
    if ($bad | length) > 0 then
        error("Replace missing or development secrets in .env (Compose environment keys): " + ($bad | join(", ")))
    elif (($env.CAMPUS_ORIGINS // "" | split(",")) | index("https://campus--erp.duckdns.org")) == null then
        error("CAMPUS_ORIGINS must include https://campus--erp.duckdns.org")
    else "Deployment configuration verified." end
'

on_error() {
    local status=$?
    trap - ERR
    printf '\nDeployment failed. Existing volumes were not removed. Inspect docker compose ps -a and docker compose logs --tail=100.\n' >&2
    "${compose[@]}" ps -a >&2 || true
    exit "$status"
}
trap on_error ERR

printf '\nPulling dependencies and building backend, workers, migrations, and frontend...\n'
"${compose[@]}" pull --ignore-buildable
"${compose[@]}" build --pull

printf '\nStarting infrastructure and applying migrations...\n'
"${compose[@]}" up -d --no-build --wait --wait-timeout 300 postgres rabbitmq fluent-bit mailpit loki prometheus grafana
"${compose[@]}" up --no-deps --no-build --force-recreate --abort-on-container-exit --exit-code-from keys keys
for service in migrate-identity migrate-academic migrate-finance migrate-hr; do
    "${compose[@]}" up --no-deps --no-build --force-recreate --abort-on-container-exit --exit-code-from "$service" "$service"
done

printf '\nStarting application containers...\n'
"${compose[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 300 identity academic finance hr academic-worker finance-worker hr-worker momo-simulator gateway backup

for endpoint in /healthz /api/v1/auth/health/ready /api/v1/academic/health/ready /api/v1/finance/health/ready /api/v1/hr/health/ready; do
    curl --fail --silent --show-error --retry 5 --retry-delay 2 --retry-connrefused --max-time 15 \
        --output /dev/null "http://127.0.0.1:8080$endpoint"
done
"${compose[@]}" ps
printf '\nDeployment healthy on 127.0.0.1:8080.\n'
printf 'Public URL after Nginx/Certbot setup: https://campus--erp.duckdns.org\n'
printf 'Initial login: institution ictu, email superadmin@campus.test. Password: CAMPUS_DEMO_PASSWORD in .env.\n'
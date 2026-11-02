#!/bin/sh
set -eu
ROOT="${TRAVELMIND_DEPLOY_ROOT:-/opt/travelmind}"
ENV_FILE="$ROOT/shared/.env"
COMPOSE="$ROOT/current/infra/vps/compose.yaml"
if [ ! -f "$ENV_FILE" ] || [ ! -f "$COMPOSE" ]; then
    echo "Initialize the deployment and current release first." >&2
    exit 1
fi
SOURCE="$(readlink -f "$ROOT/current")"
cd "$SOURCE"
dc() { docker compose --project-name travelmind --env-file "$ENV_FILE" -f "$COMPOSE" "$@" </dev/null; }
case "${1:-status}" in
    status) dc ps ;;
    sync-providers) python3 "$SOURCE/infra/vps/init.py" --root "$ROOT" --sync-providers ;;
    logs) shift; dc logs --tail=150 -f "$@" ;;
    build)
        # Separate invocations keep BuildKit from compiling three images at once.
        for service in api groksearch-bridge web; do
            dc build --print "$service" | docker buildx bake --allow=network.host --allow="fs.read=$SOURCE" --load --file - "$service"
        done
        ;;
    migrate) dc run --rm --no-deps api python -c 'from travelmind_api.core.database import init_db; init_db()' ;;
    audit) dc run --rm --no-deps api python /app/scripts/audit_workflow_rollout.py --require-drained ;;
    up) dc up -d --wait --wait-timeout 240 ;;
    restart) shift; dc restart "$@" ;;
    down) dc down ;;
    backup)
        id="$(date -u +%Y%m%dT%H%M%SZ)"
        backup="$ROOT/backups/$id"
        umask 077
        mkdir "$backup"
        # A maintenance window keeps the database and exported files aligned.
        running="$(dc ps --status running --services | grep -E '^(api|worker)$' | tr '\n' ' ' || true)"
        restore_services() {
            if [ -n "$running" ]; then
                # Only these two controlled service names are word-split.
                dc start $running >/dev/null
            fi
        }
        trap restore_services EXIT
        trap 'exit 130' HUP INT TERM
        dc stop api worker
        dc exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$backup/postgres.dump"
        tar -czf "$backup/storage.tgz" -C "$ROOT/shared" storage
        cp -p "$ENV_FILE" "$backup/app.env"
        cp -p "$ROOT/shared/providers.env" "$backup/providers.env"
        if [ -f "$ROOT/shared/backend-providers.env" ]; then
            cp -p "$ROOT/shared/backend-providers.env" "$backup/backend-providers.env"
        fi
        if [ -f "$ROOT/shared/maps.env" ]; then
            cp -p "$ROOT/shared/maps.env" "$backup/maps.env"
        fi
        if [ -f "$ROOT/shared/travel-mcp.env" ]; then
            cp -p "$ROOT/shared/travel-mcp.env" "$backup/travel-mcp.env"
        fi
        readlink -f "$ROOT/current" > "$backup/release.txt"
        echo "Root-only backup saved: $backup"
        ;;
    *) echo "Usage: travelmind {status|logs [service]|sync-providers|build|migrate|audit|up|restart [service]|backup|down}" >&2; exit 2 ;;
esac

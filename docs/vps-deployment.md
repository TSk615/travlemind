# TravelMind VPS Docker deployment

This deployment is independent of `infra/docker-compose.yml`, which remains the local development stack.
The tested target has Docker Compose 5.6 and Buildx 0.38; the build helper requires Compose's
`build --print` and Bake filesystem/network entitlement support. Build-only host-network entitlement
is explicit; it does not grant privileged containers or change daemon security settings.
It uses the migrated LangGraph backend and a shared PostgreSQL checkpoint database. It does not copy
the developer's SQLite database, accounts, historical jobs or per-user model credentials.
Default administrator-email recognition is disabled. Register the intended account first, then explicitly
set `ADMIN_EMAILS` in `shared/.env` and recreate API/Worker; do not expose a known unclaimed admin email.

## Layout

```text
/opt/travelmind/
  releases/<release-id>/       # source snapshots, immutable after deployment
  current -> releases/...     # active source/configuration
  shared/.env                 # persistent application secrets; root 0600
  shared/providers.env        # optional Grok/Tavily secrets; root 0600
  shared/backend-providers.env # generated Tavily-only API/Worker env; root 0600
  shared/postgres/            # PostgreSQL 16 data
  shared/redis/               # Redis 7 AOF
  shared/storage/             # exports, images and application logs
  shared/bridge/              # upstream GrokSearch configuration/cache
  shared/tls/                 # origin certificate and private key; root-only
  backups/<timestamp>/       # private database/files/configuration backups
```

API and Worker reuse one version-tagged backend image, locked by the API's `uv.lock`.
GrokSearch is pinned to the upstream commit used by the local environment.
Worker concurrency is two and each service has a memory and log size limit.
`providers.env` is the authoritative provider configuration. Initialization and
`travelmind sync-providers` generate a Tavily-only allowlisted `backend-providers.env`
for API/Worker, so direct evidence checks and image search can use the saved Tavily key.
Grok keys/models are deliberately not copied to backend environment variables, avoiding
implicit overrides of user-selected research models. After changing provider values,
run `travelmind sync-providers` followed by `travelmind up`; restarting alone does not
refresh container environment variables. Backups include both private provider files.

The existing host firewall drops Docker bridge forwarding. Therefore this VPS-specific stack uses
host networking **and binds every application/internal service to loopback**. Compose does not publish
PostgreSQL, Redis, API, search bridge or the frontend port to the Internet. Build networking also uses
the host. Public HTTPS is routed by a dedicated persistent Apache administrator include to the Docker
frontend; existing Resin, AdminBolt and monitoring services are not replaced.
All proxied API/export/image responses send `Cache-Control: private, no-store`, including errors.
Do not add a Cloudflare cache rule that ignores this header: private PDF/image downloads must not
be served to another user from the edge cache. Verify anonymous download denial through the public
domain, not only directly at the origin.

| Service | Local bind |
| --- | --- |
| Web | 127.0.0.1:18080 |
| API | 127.0.0.1:18000 |
| PostgreSQL | 127.0.0.1:15432 |
| Redis | 127.0.0.1:16379 |
| GrokSearch MCP bridge | 127.0.0.1:18085 |

## Initial installation

1. Copy a source archive without `.env`, private keys, databases, caches or node_modules to a new
   release directory. Keep the archive SHA256 and Git revision in a deployment manifest.
2. Run `python3 infra/vps/init.py --domain travel.rainflow.foo --release <release-id>` as root.
   Secrets are generated on the server and preserved on subsequent runs. Never regenerate the credential
   encryption key for an existing database.
3. Point `/opt/travelmind/current` at that release. Install `infra/vps/manage.sh` as `/usr/local/bin/travelmind`.
4. Put permitted search-provider values in the private `shared/providers.env`, without printing them.
5. Run `travelmind build`, then start PostgreSQL/Redis, run `travelmind migrate` and `travelmind audit`.
6. Run `travelmind up`. Validate the worker heartbeat, authenticated API and search MCP tools/list.
7. Put an appropriate certificate in `shared/tls`. Render `apache.conf.template` with the real hostname
   into `/etc/httpd/bolt-includes/post_virtualhost/60-travelmind.conf`, run `httpd -t`, then gracefully reload.
8. Add Cloudflare DNS `A travel -> 107.173.227.150`, keep it proxied, and use Full (strict) SSL.
   A Cloudflare Origin CA certificate is not publicly browser-trusted for DNS-only direct access.

## Daily maintenance

```sh
travelmind status
travelmind logs api
travelmind logs worker
travelmind audit
travelmind backup
```

`backup` briefly stops only TravelMind API/Worker, makes a custom-format PostgreSQL dump and a storage
archive, saves the corresponding encryption key/configuration, and restarts the API/Worker services
that were previously running, including on error. It does not recreate containers during backup.
Backups contain credentials and must remain root-only. Copy them off the VPS through an encrypted channel.
Do not run `docker system prune --volumes` or remove `shared` as an update procedure.

For an update, first take a backup of the active release **before** changing `current` or `RELEASE_TAG`.
Create a new release directory, run `init.py` with the new tag (keys are retained), switch `current`,
build images, stop API/Worker for the migration, migrate/audit, and then start the new release.
Keep old source and images for
rollback. Database rollback requires reviewing migration compatibility and, if needed, restoring the
matching database dump **and** secret configuration during maintenance; do not blindly switch images
across incompatible schemas. Historical local SQLite data migration is a separate explicit operation.

## Acceptance scope

Health endpoints alone are insufficient. Check database revision/drain audit, worker heartbeat,
registration/login/Secure cookies/CSRF, same-origin API/static assets and an ARQ job (for example PDF
export). Check MCP initialization/tools/list without issuing bulk model requests. Keep the full
LangGraph quality/cost release gates from `langgraph-migration-verification-2026-09-20.md`; a deployment
smoke test does not replace the retained baseline and 30-case quality gate. Newly registered users must
configure their model/role credentials before real itinerary generation.

## Optional hotel / railway MCP credentials (2026-10-28)

Keep read-only travel MCP settings in root-only `shared/travel-mcp.env`, not a release archive or the bridge/web environment. `travelmind sync-providers` allowlists `TRAVELMIND_{HOTEL,RAILWAY}_MCP_{ENABLED,URL,TOKEN,TIMEOUT_SECONDS}` into `backend-providers.env`; then `travelmind up` recreates API/Worker with the new environment. The Docker `raw` env-file setting preserves literal token characters. Do not copy developer-local CONFIG_FILE paths into production. `travelmind backup` now includes the private travel-MCP file. Neither provider is an order/payment integration. ModelScope connection expiration still needs operator attention; there is no automatic renewal.

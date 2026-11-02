"""Initialize root-only VPS configuration without rotating existing secrets."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets


BACKEND_PROVIDER_KEYS = frozenset({
    "TAVILY_API_KEY", "TAVILY_API_URL", "TRAVELMIND_TAVILY_API_KEY",
    "TRAVELMIND_TAVILY_BASE_URL", "TRAVELMIND_TAVILY_TIMEOUT_SECONDS",
    "TRAVELMIND_TAVILY_IMAGE_INCLUDE_DOMAINS",
})


def sync_backend_providers(shared: Path) -> None:
    """Copy allowlisted backend providers, never Grok overrides or maps keys to bridge."""
    source = shared / "providers.env"
    entries = {}
    if source.exists():
        for line in source.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in BACKEND_PROVIDER_KEYS:
                entries[key] = value
    # Maps credentials belong to API/worker only, not the search bridge or web.
    maps_source = shared / "maps.env"
    map_keys = {"TRAVELMIND_MAPS_PROVIDER", "TRAVELMIND_AMAP_API_KEY", "TRAVELMIND_AMAP_BASE_URL",
                "TRAVELMIND_AMAP_TIMEOUT_SECONDS", "TRAVELMIND_AMAP_MAX_HTTP_CALLS",
                "TRAVELMIND_AMAP_MIN_INTERVAL_SECONDS"}
    if maps_source.exists():
        for line in maps_source.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in map_keys:
                entries[key] = value
    # Private read-only travel MCP credentials belong to API/worker, never web/bridge.
    mcp_keys = {
        f"TRAVELMIND_{kind}_MCP_{suffix}"
        for kind in ("RAILWAY", "HOTEL")
        for suffix in ("ENABLED", "URL", "TOKEN", "TIMEOUT_SECONDS")
    }
    mcp_source = shared / "travel-mcp.env"
    if mcp_source.exists():
        for line in mcp_source.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key in mcp_keys:
                entries[key] = value
    temporary = shared / "backend-providers.env.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("# Generated API/Worker provider configuration; do not commit.\n")
        stream.writelines(f"{key}={value}\n" for key, value in sorted(entries.items()))
    destination = shared / "backend-providers.env"
    os.replace(temporary, destination)
    destination.chmod(0o600)


def initialize(root: Path, domain: str, release: str) -> None:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or "." not in domain:
        raise ValueError("A DNS hostname, without scheme or port, is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", release):
        raise ValueError("Invalid release tag")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    shared = root / "shared"
    shared.mkdir(exist_ok=True, mode=0o700)
    env_path = shared / ".env"
    keys = ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "CREDENTIAL_ENCRYPTION_KEY", "BRIDGE_API_KEY")
    if env_path.exists():
        values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line and not line.startswith("#"))
        if any(not values.get(key) for key in keys):
            raise ValueError("Existing secret configuration is incomplete; refusing to rotate secrets")
    else:
        values = {key: secrets.token_hex(32) for key in keys}
    values.setdefault("ADMIN_EMAILS", "")
    values.update(APP_DOMAIN=domain, DEPLOY_ROOT=str(root), RELEASE_TAG=release)
    temporary = shared / ".env.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("# Private deployment configuration. Back up this file with the database.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    os.replace(temporary, env_path)
    env_path.chmod(0o600)
    for relative, uid in (("storage", 10001), ("bridge", 10001), ("redis", 10002), ("postgres", 0)):
        path = shared / relative
        existed = path.exists()
        path.mkdir(exist_ok=True, mode=0o700)
        # PostgreSQL's entrypoint owns an existing data directory. Do not take
        # ownership away from a running database during release initialization.
        if hasattr(os, "chown") and (relative != "postgres" or not existed):
            os.chown(path, uid, uid)
    for relative in ("exports", "images", "logs"):
        path = shared / "storage" / relative
        path.mkdir(exist_ok=True, mode=0o700)
        if hasattr(os, "chown"):
            os.chown(path, 10001, 10001)
    redis_config = (
        "bind 127.0.0.1\nprotected-mode yes\nport 16379\ndir /data\n"
        "appendonly yes\nappendfsync everysec\nsave 60 1000\n"
        "maxmemory 96mb\nmaxmemory-policy noeviction\n"
        f"requirepass {values['REDIS_PASSWORD']}\n"
    )
    for name, content in (("redis.conf", redis_config), ("redis-password", values["REDIS_PASSWORD"] + "\n")):
        path = shared / name
        path.write_text(content)
        path.chmod(0o400)
        if hasattr(os, "chown"):
            os.chown(path, 10002, 10002)
    provider_env = shared / "providers.env"
    if not provider_env.exists():
        provider_env.write_text("# Optional Grok/Tavily credentials; root-only, never in the source archive.\n")
    provider_env.chmod(0o600)
    sync_backend_providers(shared)
    (root / "backups").mkdir(exist_ok=True, mode=0o700)
    print(f"Initialized {root}; domain={domain}; release={release}. No secrets displayed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/travelmind"))
    parser.add_argument("--domain")
    parser.add_argument("--release")
    parser.add_argument("--sync-providers", action="store_true")
    args = parser.parse_args()
    if args.sync_providers:
        sync_backend_providers(args.root.resolve() / "shared")
        print("Synchronized Tavily-only backend configuration. No secrets displayed.")
    else:
        if not args.domain or not args.release:
            parser.error("--domain and --release are required for initialization")
        initialize(args.root, args.domain.strip().lower(), args.release)

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from travelmind_api.core.config import Settings

_NUMERIC_HOST_PATTERN = re.compile(r"^[0-9.]+$")
_METADATA_HOSTS = {"metadata.google.internal"}
_INTERNAL_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home", ".corp")


class UpstreamUrlError(ValueError):
    pass


def normalize_upstream_base_url(base_url: str | None, settings: Settings) -> str | None:
    candidate = str(base_url or "").strip().rstrip("/")
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise UpstreamUrlError("base_url must be a valid http or https URL")
    if parsed.username or parsed.password:
        raise UpstreamUrlError("base_url must not include username or password")

    _validate_upstream_host(parsed.hostname, settings)
    return candidate


def _validate_upstream_host(hostname: str, settings: Settings) -> None:
    host = hostname.strip().lower().rstrip(".")
    if not host:
        raise UpstreamUrlError("base_url must include a hostname")

    if host in _normalized_allowed_hosts(settings):
        return

    policy = _normalized_private_policy(settings)
    if policy == "allow":
        return

    classification = _classify_host(host)
    if classification == "public":
        return
    if classification == "loopback" and policy == "loopback":
        return

    raise UpstreamUrlError(
        "base_url points to a private, local, or otherwise restricted network address; "
        "use a public upstream URL or explicitly allow the host in deployment settings"
    )


def _normalized_private_policy(settings: Settings) -> str:
    policy = str(settings.upstream_private_url_policy or "loopback").strip().lower()
    return policy if policy in {"allow", "loopback", "deny"} else "loopback"


def _normalized_allowed_hosts(settings: Settings) -> set[str]:
    raw = str(settings.upstream_url_allowed_hosts or "")
    hosts: set[str] = set()
    for item in re.split(r"[\s,;]+", raw):
        candidate = item.strip().lower().rstrip(".")
        if candidate:
            hosts.add(candidate)
    return hosts


def _classify_host(host: str) -> str:
    if host in {"localhost", "ip6-localhost", "ip6-loopback"} or host.endswith(".localhost"):
        return "loopback"
    if host in _METADATA_HOSTS:
        return "restricted"

    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if _NUMERIC_HOST_PATTERN.fullmatch(host):
            return "restricted"
        if "." not in host or host.endswith(_INTERNAL_HOST_SUFFIXES):
            return "restricted"
        return "public"

    if address.is_loopback:
        return "loopback"
    if (
        address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return "restricted"
    return "public"

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from travelmind_api.core.env import get_env

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExaPoolConfig:
    base_url: str
    api_key: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> ExaPoolConfig | None:
        import os

        base_url = (get_env("TRAVELMIND_EXA_POOL_BASE_URL") or "").strip().rstrip("/")
        api_key = (get_env("TRAVELMIND_EXA_POOL_API_KEY") or "").strip()
        timeout_raw = (get_env("TRAVELMIND_EXA_POOL_TIMEOUT_SECONDS") or "30").strip()
        if not base_url or not api_key:
            return None
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 30.0
        return cls(base_url=base_url, api_key=api_key, timeout_seconds=timeout_seconds)


class ExaPoolClientError(RuntimeError):
    pass


class ExaPoolClient:
    def __init__(self, config: ExaPoolConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client

    def search(
        self,
        *,
        query: str,
        num_results: int = 10,
        search_type: str = "auto",
        include_text: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query.strip(),
            "numResults": int(num_results),
            "type": search_type,
        }
        if include_text:
            payload["contents"] = {"text": True}
        return self._post("/search", payload)

    def contents(
        self,
        *,
        urls: list[str],
        include_text: bool = True,
        include_html: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "urls": urls,
            "text": include_text,
        }
        if include_html:
            payload["htmlContent"] = True
        return self._post("/contents", payload)

    def find_similar(
        self,
        *,
        url: str,
        num_results: int = 10,
        include_text: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": url.strip(),
            "numResults": int(num_results),
        }
        if include_text:
            payload["contents"] = {"text": True}
        return self._post("/findSimilar", payload)

    def answer(self, *, query: str, include_text: bool = False) -> dict[str, Any]:
        payload = {
            "query": query.strip(),
            "text": include_text,
        }
        return self._post("/answer", payload)

    def research(
        self,
        *,
        instructions: str,
        model: str = "exa-research",
        wait_for_completion: bool = True,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 45.0,
    ) -> dict[str, Any]:
        payload = {
            "instructions": instructions.strip(),
            "model": model,
        }
        created = self._post("/research/v1", payload)
        if not wait_for_completion:
            return created

        research_id = str(created.get("researchId") or created.get("id") or "").strip()
        if not research_id:
            return created

        deadline = time.time() + max_wait_seconds
        latest = created
        while time.time() < deadline:
            latest = self.get_research(research_id=research_id)
            status = str(latest.get("status") or "").strip().lower()
            if status in {"completed", "complete", "done", "failed", "error"}:
                return latest
            time.sleep(poll_interval_seconds)
        latest["status"] = latest.get("status") or "timeout"
        latest["timeout"] = True
        return latest

    def get_research(self, *, research_id: str) -> dict[str, Any]:
        return self._get(f"/research/v1/{research_id.strip()}")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._config.api_key,
            "Content-Type": "application/json",
            "User-Agent": "travelmind-exa-pool/0.1.0",
        }

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", endpoint, json=payload)

    def _get(self, endpoint: str) -> dict[str, Any]:
        return self._request("GET", endpoint)

    def _request(self, method: str, endpoint: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._config.base_url.rstrip('/')}{endpoint}"
        print(f"[EXA] {method} {url} payload_keys={sorted((json or {}).keys())}")
        if self._http_client is not None:
            response = self._http_client.request(method, url, headers=self._headers(), json=json)
        else:
            with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                response = client.request(method, url, headers=self._headers(), json=json)
        print(f"[EXA] {method} {url} -> {response.status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:400]
            print(f"[EXA] {method} {url} failed status={exc.response.status_code} body={detail}")
            raise ExaPoolClientError(f"Exa Pool request failed [{exc.response.status_code}] {exc.response.reason_phrase}: {detail}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            preview = response.text[:400]
            print(f"[EXA] {method} {url} returned non-JSON body={preview}")
            raise ExaPoolClientError(f"Exa Pool response was not valid JSON: {preview}") from exc
        if not isinstance(payload, dict):
            raise ExaPoolClientError("Exa Pool response root must be an object")
        return payload

from __future__ import annotations

import json
import sys

from travelmind_api.services.mcp import McpClientConfig, McpHttpClient


def main() -> int:
    config = McpClientConfig.from_env()
    if config is None:
        print("TRAVELMIND_MCP_BASE_URL / TRAVELMIND_MCP_API_KEY 未配置")
        return 1

    client = McpHttpClient(config)
    tools = client.list_tools(force_refresh=True)
    print(json.dumps({"base_url": config.base_url, "tools": tools}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

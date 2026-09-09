#!/usr/bin/env python3
"""
快速测试脚本:触发一次广州→大理行程生成,验证 Grok answer POI 池路径。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

# 添加 src 到 path
sys.path.insert(0, str(Path(__file__).parent / "apps" / "api" / "src"))

from travelmind_api.agents.helloagents import HelloAgentsOrchestrator, HelloAgentsCompatibleLLM
from travelmind_api.core.models import PlanningRequest
from travelmind_api.services.maps import build_maps_provider
from travelmind_api.services.search_connector import SearchGateway, SearchServiceConfig

def main():
    # 构造广州→大理请求(复现 job_637b7132ccd938bae4d2)
    request = PlanningRequest(
        trip_id="trip_test_grok_poi",
        title="广州出发去大理",
        origin="广州",
        destination="大理",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        budget=6800,
        travelers=2,
        interests=["美食", "城市漫步", "海边风景"],
        accommodation_preference="靠近市区、方便步行觅食的酒店",
        pace="balanced",
        transport_mode="rail",
        locale="zh-CN",
    )

    # 构建 LLM 配置(从环境变量取,默认 token-plan-cn)
    llm_config = HelloAgentsCompatibleLLM(
        base_url=os.getenv("TRAVELMIND_LLM_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
        api_key=os.getenv("TRAVELMIND_LLM_API_KEY", ""),
        model=os.getenv("TRAVELMIND_LLM_MODEL", "mimo-v2-pro"),
        timeout_seconds=300,  # 给足够时间,避免 timeout
    )

    # 构建 search gateway(从环境变量取,默认 groksearch MCP)
    search_config = SearchServiceConfig(
        provider=os.getenv("TRAVELMIND_SEARCH_PROVIDER", "groksearch"),
        mcp_server_name=os.getenv("TRAVELMIND_SEARCH_MCP_SERVER_NAME", "groksearch"),
    )
    search_gateway = SearchGateway(search_config)

    # 构建 maps provider
    maps_provider = build_maps_provider()

    # 创建 orchestrator
    orchestrator = HelloAgentsOrchestrator(
        llm_config=llm_config,
        search_gateway=search_gateway,
        maps_provider=maps_provider,
    )

    print(f"=== 开始生成行程 ===")
    print(f"目的地: {request.destination}")
    print(f"LLM: {llm_config.model} @ {llm_config.base_url}")
    print(f"Search: {search_config.provider} (MCP: {search_config.mcp_server_name})")
    print(f"Maps: {maps_provider.provider_name}")
    print()

    # 执行生成
    try:
        result = orchestrator.plan_trip(request)
        print(f"=== 生成成功 ===")
        print(f"行程天数: {len(result.days)}")
        print(f"预算: {result.total_budget_estimate}")
        print(f"Workflow ID: {result.trace.workflow_id}")

        # 输出 POI 相关信息(验证 grok_answer 路径)
        if result.trace.agent_runs:
            for run in result.trace.agent_runs:
                if run.role == "poi_specialist":
                    print(f"\n=== POI Specialist 执行信息 ===")
                    print(f"状态: {run.status}")
                    print(f"耗时: {run.elapsed_seconds:.1f}s")
                    if run.output_snapshot:
                        poi_source = run.output_snapshot.get("poi_source", "未知")
                        featured_count = run.output_snapshot.get("featured_poi_count", 0)
                        print(f"POI 来源: {poi_source}")
                        print(f"Featured POI 数量: {featured_count}")
                    break

        print(f"\n查看完整日志: logs/jobs/{result.trace.workflow_id.replace('workflow_', 'job_')}.jsonl")

    except Exception as exc:
        print(f"=== 生成失败 ===")
        print(f"错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

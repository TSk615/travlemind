from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROLE_LABELS = {
    "brief_parser": "阶段 1：需求摘要",
    "poi_specialist": "阶段 2：POI 搜索",
    "weather_specialist": "阶段 3：天气搜索",
    "hotel_specialist": "阶段 4：酒店搜索",
    "transport_specialist": "阶段 5：交通搜索",
    "itinerary_planner": "阶段 6：最终行程规划",
}


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def fenced(value: str, language: str = "text") -> str:
    return f"````{language}\n{value.rstrip()}\n````"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    audit = json.loads(args.input.read_text(encoding="utf-8"))
    output = args.output or args.input.with_suffix(".md")
    lines = [
        "# TravelMind Agent 完整调用审计",
        "",
        f"- 行程 ID：`{audit.get('trip_id')}`",
        f"- 任务 ID：`{audit.get('job_id')}`",
        f"- 任务状态：`{audit.get('job_status')}`",
        f"- 行程标题：{audit.get('trip_title') or ''}",
        f"- 审计生成时间：`{audit.get('created_at')}`",
        "- 内容说明：每个阶段依次列出系统提示词、实际输入、原始返回和解析后返回；未记录 API Key。",
        "",
    ]

    for index, record in enumerate(audit.get("records", []), start=1):
        role = record.get("role", "unknown")
        lines.extend(
            [
                f"## {ROLE_LABELS.get(role, f'阶段 {index}：{role}')}",
                "",
                f"- 角色：`{role}`",
                f"- 模型：`{record.get('model')}`",
                f"- 调用协议：`{record.get('wire_api')}`",
                f"- 服务协议：`{record.get('provider_protocol')}`",
                "",
                "### 系统提示词",
                "",
                fenced(str(record.get("system_prompt") or "")),
                "",
                "### 实际输入 payload",
                "",
                fenced(json_text(record.get("input_payload")), "json"),
                "",
                "### 原始模型返回",
                "",
                fenced(str(record.get("raw_return") or record.get("error") or ""), "json"),
                "",
                "### 解析后返回",
                "",
                fenced(json_text(record.get("parsed_return")), "json"),
                "",
            ]
        )

    lines.extend(
        [
            "## 最终落库行程",
            "",
            fenced(json_text(audit.get("final_itinerary")), "json"),
            "",
            "## 最终 Agent 追踪",
            "",
            fenced(json_text(audit.get("final_agent_trace")), "json"),
            "",
            "## 任务结果",
            "",
            fenced(json_text(audit.get("job_result")), "json"),
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    print(str(output.resolve()))


if __name__ == "__main__":
    main()

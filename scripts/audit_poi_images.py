"""Replay image enrichment only; do not modify saved user trips or call planners."""
import argparse
import json
from io import BytesIO
from datetime import datetime
from pathlib import Path
import httpx
from PIL import Image, ImageDraw

from travelmind_api.agents.base import PlanningRequest, PlanningResult
from travelmind_api.services.search_connector import SearchServiceConfig
from travelmind_api.services.trip_image_enrichment import enrich_plan_images
from travelmind_api.services.image_validation import public_image_url, inspect_image_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audit")
    parser.add_argument("--review-user-id", help="Read this user's saved main model for visual review; no user data is modified")
    parser.add_argument("--poi", action="append", default=[], help="Only replay sight names containing this text")
    args = parser.parse_args()
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    plan = PlanningResult.model_validate({**audit["final_itinerary"], "trace": audit["final_agent_trace"]})
    if args.poi:
        for day in plan.days:
            day.items = [item for item in day.items if item.type == "sight" and any(name in item.name for name in args.poi)]
    review_config = None
    if args.review_user_id:
        from travelmind_api.core.database import SessionLocal
        from travelmind_api.db.models import User
        from travelmind_api.jobs.handlers import _resolve_llm_config
        with SessionLocal() as session:
            user = session.query(User).filter(User.id == args.review_user_id).one()
            review_config = _resolve_llm_config(user, {})
        if review_config is None:
            raise RuntimeError("该用户未配置审核模型，未发送图片")
    request = PlanningRequest(
        trip_id="image_audit", title="上海景点补图验收", origin="广州", destination="上海",
        start_date="2026-09-20", end_date="2026-09-22", budget=6800, travelers=2,
        interests=["历史建筑"], accommodation_preference="中档", pace="balanced", transport_mode="rail",
        locale="zh-CN",
    )
    result = enrich_plan_images(plan, request, search_service=SearchServiceConfig.from_env(), force=True,
                                review_config=review_config)
    target = Path(".tmp/agent-audit") / f"shanghai-images-{datetime.now():%Y%m%d-%H%M%S}.json"
    target.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    sheet = Image.new("RGB", (1000, 350 * 3), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(item for day in result.days for item in day.items if item.type == "sight"):
        x, y = (index % 2) * 500, (index // 2) * 350
        draw.text((x + 12, y + 8), f"POI {index+1} - {item.image_status}", fill="black")
        if item.image_urls and public_image_url(item.image_urls[0]):
            try:
                response = httpx.get(item.image_urls[0], timeout=10, follow_redirects=False, trust_env=False)
                response.raise_for_status()
                inspect_image_bytes(response.content)
                picture = Image.open(BytesIO(response.content)).convert("RGB")
                picture.thumbnail((480, 310))
                sheet.paste(picture, (x + 10, y + 30))
            except Exception as exc:
                draw.text((x + 12, y + 40), type(exc).__name__, fill="red")
    sheet.save(target.with_suffix(".jpg"))
    print(json.dumps({"audit_path": str(target), "items": [
        {"name": item.name, "status": item.image_status, "images": item.image_urls,
         "sources": item.image_source_urls, "error": item.image_failure_reason}
        for day in result.days for item in day.items if item.type == "sight"
    ]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

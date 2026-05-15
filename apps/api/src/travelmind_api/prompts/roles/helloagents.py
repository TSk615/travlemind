from __future__ import annotations

import json
from typing import Any

from travelmind_api.prompts.types import RolePromptSpec

BRIEF_PARSER_PROMPT_VERSION = "helloagents.brief_parser.v2"
ATTRACTION_SPECIALIST_PROMPT_VERSION = "helloagents.attraction_specialist.v2"
WEATHER_SPECIALIST_PROMPT_VERSION = "helloagents.weather_specialist.v3"
HOTEL_SPECIALIST_PROMPT_VERSION = "helloagents.hotel_specialist.v2"
TRANSPORT_SPECIALIST_PROMPT_VERSION = "helloagents.transport_specialist.v1"
ITINERARY_PLANNER_PROMPT_VERSION = "helloagents.itinerary_planner.v2"
IMAGE_CURATOR_PROMPT_VERSION = "helloagents.image_curator.v1"
IMAGE_QUERY_PLANNER_PROMPT_VERSION = "helloagents.image_query_planner.v1"
IMAGE_REVIEWER_PROMPT_VERSION = "helloagents.image_reviewer.v1"


BRIEF_OUTPUT_SCHEMA: dict[str, Any] = {
    "destination": "Kyoto",
    "trip_days": 2,
    "budget_band": "midrange",
    "budget_is_hard_constraint": True,
    "budget_priority": "balance tickets and transport before adding optional upgrades",
    "allow_budget_flex": False,
    "pace": "balanced",
    "must_have": ["temples", "coffee"],
    "avoid": ["overpacked long-distance transfers"],
    "transport": "rail",
    "accommodation": "quiet boutique hotel",
    "interests": ["temples", "coffee"],
    "planning_constraints": ["keep sequencing realistic", "respect budget and pace"],
}

ATTRACTION_OUTPUT_SCHEMA: dict[str, Any] = {
    "candidate_areas": ["Higashiyama", "Downtown Kyoto"],
    "featured_pois": [
        {
            "name": "Ginkaku-ji",
            "area": "Higashiyama",
            "reason": "Fits a calm scenic morning.",
            "suggested_time": "morning",
            "booking_info": {
                "price_label": "Adult ticket around 500 JPY",
                "estimated_price": 25.0,
                "booking_required": False,
                "reservation_required": False,
                "official_booking_url": "",
                "booking_window": "",
                "reminder": "",
                "notes": ["Leave the booking URL blank if you cannot verify an official page."],
                "source_urls": [],
            },
            "visit_requirements": {
                "reservation_policy": "not_needed",
                "timed_entry": False,
                "identity_required": False,
                "advance_booking_note": "",
                "notes": ["Mention closures, timed entry, or capacity controls when known."],
            },
        }
    ],
    "sequencing_hints": ["Group nearby sights in the same half-day block."],
    "crowd_notes": ["Popular sights may require early arrival."],
    "attraction_risks": ["Long cross-city transfers will hurt pacing."],
}

WEATHER_OUTPUT_SCHEMA: dict[str, Any] = {
    "overall_outlook": "Spring conditions around 18°C to 24°C, with cool mornings, mild afternoons, and occasional light rain.",
    "daily_outlook": ["Day 1: 18°C to 24°C, cool morning and mild afternoon."],
    "packing_notes": ["Carry a light layer and compact umbrella."],
    "timing_guidance": ["Outdoor walks work best in the late morning and early afternoon."],
    "weather_risks": ["Light rain may affect exposed outdoor stops."],
}

HOTEL_OUTPUT_SCHEMA: dict[str, Any] = {
    "recommended_areas": ["Downtown Kyoto", "Higashiyama"],
    "hotel_candidates": [
        {
            "name": "Downtown Kyoto Hotel",
            "area": "Downtown Kyoto",
            "reason": "Balanced access to food and transit.",
            "price_hint": "moderate",
        }
    ],
    "stay_strategy": ["Prefer a transit-friendly base that minimizes cross-city transfers."],
    "budget_notes": ["Keep the hotel near the target nightly budget band."],
}

TRANSPORT_OUTPUT_SCHEMA: dict[str, Any] = {
    "intercity_options": [
        {
            "mode": "high_speed_rail",
            "route": "Osaka -> Kyoto Station",
            "duration_hint": "about 15 to 30 minutes depending on departure point",
            "price_hint": "roughly within the current budget assumptions",
            "booking_window": "Reserve early during peak periods",
            "reason": "Fastest practical rail transfer with limited friction.",
            "official_booking_url": "",
            "booking_required": False,
            "reservation_required": False,
            "booking_notes": ["Prefer the operator or official rail booking page when available."],
        }
    ],
    "arrival_strategy": ["Match the arrival station or airport transfer to the hotel area and first-day pacing."],
    "local_mobility_strategy": ["Use the transit option that keeps hotel-to-sight transfers predictable and short."],
    "pass_or_ticket_notes": ["Only recommend a pass when it is likely to beat point-to-point tickets."],
    "budget_notes": ["Keep transport estimates conservative and aligned with the trip budget."],
    "transport_risks": ["Peak departures can sell out or become crowded."],
    "sequencing_constraints": ["Keep departure-day activities close to the final transfer corridor."],
    "estimated_intercity_cost": 280.0,
    "estimated_local_transport_cost": 45.0,
    "summary": "Rail is the best fit for this trip's budget and pacing.",
    "recommended_option": "Osaka to Kyoto Station by rail",
    "booking_required": False,
    "official_booking_url": "",
    "booking_window": "Reserve early during peak periods",
    "reminders": ["Leave the URL blank instead of inventing a booking page."],
    "notes": ["Explain uncertainty instead of over-precise fare promises."],
    "source_urls": [],
}

IMAGE_CURATOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "items": [
        {
            "item_id": "item_123",
            "priority_tier": "high",
            "reason": "A city-defining landmark with strong visual identity and cover-image potential.",
            "suggested_image_count": 3,
        }
    ]
}

IMAGE_QUERY_PLANNER_OUTPUT_SCHEMA: dict[str, Any] = {
    "canonical_name": "The Bund",
    "aliases": ["外滩", "Shanghai Bund"],
    "search_queries": [
        "\"The Bund\" Shanghai landmark official travel photos",
        "\"外滩\" 上海 景点 官方 旅游 图片",
    ],
    "reason": "Use the real attraction name from the itinerary instead of generic map placeholders.",
}

IMAGE_REVIEWER_OUTPUT_SCHEMA: dict[str, Any] = {
    "selected_candidates": [
        {
            "candidate_id": "c1",
            "reason": "This image clearly shows the actual landmark rather than a city-generic skyline or a page asset.",
            "confidence": "high",
        }
    ],
    "rejected_candidates": [
        {
            "candidate_id": "c2",
            "reason": "This looks like a page decoration, logo, or generic cover image rather than the attraction itself.",
        }
    ],
    "summary": "Selected the candidates that clearly depict the attraction itself and rejected page chrome or generic city visuals.",
}


# 中文注释：
# - 角色：brief parser
# - 目标：把用户原始 trip request 压缩成结构化 planning brief。
# - 禁止：不要直接开始写最终 itinerary。
def build_brief_parser_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Brief Parser. Return one compact planning brief JSON object only. "
        "No markdown, no commentary, no itinerary drafting. "
        "Make the budget rule explicit: capture whether the budget behaves like a hard constraint, what the main cost priority is, and whether small over-budget tradeoffs are allowed. "
        f"Use this schema shape: {json.dumps(BRIEF_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=BRIEF_PARSER_PROMPT_VERSION, system_prompt=system_prompt)


# 中文注释：
# - 角色：attraction specialist
# - 目标：基于 brief 和外部检索结果，给出景点区域、候选 POI 和顺序建议。
# - 禁止：不要越权生成完整 itinerary。
def build_attraction_specialist_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Attraction Specialist. Return one attraction-grounding JSON object only. "
        "You will receive structured MCP search results in the input payload under tool_results. "
        "Prioritize realistic areas, featured POIs, and sequencing advice for the trip interests. "
        "For each featured POI, include grounded ticket or entry information, reservation requirements, official-first booking URLs, and reminder notes when they are supported by the source material. "
        "If you cannot verify an official booking page, leave the booking URL blank and use notes to explain the uncertainty. "
        f"Use this schema shape: {json.dumps(ATTRACTION_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=ATTRACTION_SPECIALIST_PROMPT_VERSION, system_prompt=system_prompt)


# 中文注释：
# - 角色：weather specialist
# - 目标：输出“规划用途”的天气建议，而不是假装给实时天气预报。
# - 要点：强调 seasonal guidance、打包建议、时段建议和天气风险。
def build_weather_specialist_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Weather Specialist. Return one weather-guidance JSON object only. "
        "You will receive structured MCP search results in the input payload under tool_results. "
        "Use planning-level seasonal guidance for the provided destination and dates. "
        "When the source material includes temperature guidance, explicitly include approximate daily temperature ranges in overall_outlook and daily_outlook. "
        "Do not claim to have live forecast certainty, and keep all notes actionable for itinerary planning. "
        f"Use this schema shape: {json.dumps(WEATHER_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=WEATHER_SPECIALIST_PROMPT_VERSION, system_prompt=system_prompt)


# 中文注释：
# - 角色：hotel specialist
# - 目标：结合预算、交通负担、住宿偏好，给出住哪里更合理。
# - 禁止：不要直接合成最终 itinerary，只输出住宿建议 JSON。
def build_hotel_specialist_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Hotel Specialist. Return one hotel-recommendation JSON object only. "
        "You will receive structured MCP search results in the input payload under tool_results. "
        "Focus on stay areas, candidate hotels, and stay strategy that reduce transfer burden and match the trip style. "
        f"Use this schema shape: {json.dumps(HOTEL_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=HOTEL_SPECIALIST_PROMPT_VERSION, system_prompt=system_prompt)


def build_transport_specialist_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Transport Specialist. Return one transport-guidance JSON object only. "
        "You will receive structured MCP search results in the input payload under tool_results. "
        "Focus on realistic intercity and local transport choices, transfer sequencing, and grounded pricing guidance. "
        "Use the same implied budget currency as the trip request when you provide numeric cost estimates. "
        "If price signals are uncertain, stay conservative, explain the constraint in notes, and avoid inventing over-precise fares. "
        "Prefer official booking URLs. If you cannot verify one, leave the URL blank and explain the uncertainty in notes or reminders. "
        f"Use this schema shape: {json.dumps(TRANSPORT_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=TRANSPORT_SPECIALIST_PROMPT_VERSION, system_prompt=system_prompt)


# 中文注释：
# - 角色：itinerary planner
# - 目标：汇总 brief / attractions / weather / hotel 四份结构化输入，生成最终 itinerary。
# - 说明：这里复用主规划 prompt，再额外补一段多角色汇总说明。
def build_itinerary_planner_prompt(planner_system_prompt: str) -> RolePromptSpec:
    system_prompt = (
        f"{planner_system_prompt} "
        "You will receive a structured planning brief, an attraction specialist package, a weather specialist package, a hotel specialist package, and a transport specialist package. "
        "Treat grounded prices, booking constraints, and reservation feasibility as strong planning constraints rather than soft suggestions. "
        "Prefer itinerary choices that stay within budget and remain bookable or reserve-able from official sources when available. "
        "Use all of them to generate the final itinerary draft."
    )
    return RolePromptSpec(version=ITINERARY_PLANNER_PROMPT_VERSION, system_prompt=system_prompt)


def build_image_curator_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Image Curator. Return one JSON object only. "
        "Decide which itinerary items deserve the strongest visual treatment in the final guide. "
        "Judge using only itinerary text and trip context, not candidate images. "
        "Consider landmark value, visual distinctiveness, relevance to the user's interests, whether the stop is a core memory point for the day, "
        "and whether it could serve as a hero image in the final trip guide. "
        "Allowed priority_tier values are high, medium, low, and skipped. "
        "suggested_image_count must be 0, 1, 2, or 3. "
        "Use skipped with 0 images for items that do not need visual coverage such as transfers or low-importance functional stops. "
        f"Use this schema shape: {json.dumps(IMAGE_CURATOR_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=IMAGE_CURATOR_PROMPT_VERSION, system_prompt=system_prompt)


def build_image_query_planner_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Image Query Planner. Return one JSON object only. "
        "You will receive one itinerary item plus trip context. "
        "Your job is to identify the real attraction subject that should be used for image search, not a generic map placeholder, not a surrounding district, and not an activity suffix. "
        "Prefer the actual attraction or district name used in the itinerary item text. "
        "Remove strategy suffixes such as repeat visit, hotel-area walk, nearby stroll, return visit, or generic walking labels when they are not the actual attraction name. "
        "When useful, provide bilingual aliases or common alternate names. "
        "Generate 1 to 3 search_queries that are tightly focused on the attraction itself. "
        f"Use this schema shape: {json.dumps(IMAGE_QUERY_PLANNER_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=IMAGE_QUERY_PLANNER_PROMPT_VERSION, system_prompt=system_prompt)


def build_image_reviewer_prompt() -> RolePromptSpec:
    system_prompt = (
        "You are TravelMind Image Reviewer. Return one JSON object only. "
        "You will receive one attraction plus a small set of candidate image URLs and their source metadata. "
        "Judge whether each image is truly about the attraction itself. "
        "Reject images that are logos, banners, UI assets, social-share cards, QR codes, generic city skylines, event posters, ads, or page decorations. "
        "Prefer images where the attraction itself is clearly visible, visually representative, and suitable for a travel guide. "
        "Only keep high-confidence candidates. It is acceptable to return zero selected candidates if none are reliable enough. "
        "Use candidate IDs exactly as given. "
        f"Use this schema shape: {json.dumps(IMAGE_REVIEWER_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    return RolePromptSpec(version=IMAGE_REVIEWER_PROMPT_VERSION, system_prompt=system_prompt)

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from travelmind_api.agents.base import ExportDraft, PlannedDay, PlanningRequest, PlanningResult
from travelmind_api.core.config import Settings
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.llm.localization import is_chinese_output


EXPORT_FILES_ROUTE = "/exports/files"
SUPPORTED_EXPORT_FORMATS = ("md", "pdf", "json")
_PDF_FONT_NAME = "STSong-Light"
_PAGE_WIDTH, _ = A4
_SECTION_GAP = 5 * mm
_CARD_BACKGROUND = colors.HexColor("#F7F6F2")
_BORDER_COLOR = colors.HexColor("#D4CFC4")
_ACCENT_COLOR = colors.HexColor("#31525B")
_MUTED_TEXT = colors.HexColor("#5F6B6D")
_ITEM_COST_WEIGHTS = {
    "sight": 1.2,
    "photo": 1.0,
    "meal": 1.1,
    "food": 1.1,
    "hotel": 1.6,
    "stay": 1.6,
    "transit": 0.7,
    "transport": 0.7,
    "explore": 0.9,
}


@dataclass(frozen=True)
class ExportField:
    label: str
    value: str


@dataclass(frozen=True)
class ExportItemView:
    time_range: str
    title: str
    meta: str
    estimated_cost: str
    details: list[str]


@dataclass(frozen=True)
class ExportDayView:
    heading: str
    summary: str
    facts: list[str]
    items: list[ExportItemView]


@dataclass(frozen=True)
class ExportBudgetLineView:
    title: str
    amount: str
    note: str | None = None


@dataclass(frozen=True)
class ExportDocumentView:
    title: str
    subtitle: str
    handbook_label: str
    summary_title: str
    summary_text: str
    basics_title: str
    basic_fields: list[ExportField]
    overview_title: str
    overview_fields: list[ExportField]
    itinerary_title: str
    days: list[ExportDayView]
    budget_title: str
    budget_fields: list[ExportField]
    budget_breakdown_fields: list[ExportField]
    budget_lines_title: str
    budget_lines: list[ExportBudgetLineView]
    booking_title: str
    transport_booking_title: str
    transport_booking_fields: list[ExportField]
    reservation_lines_title: str
    reservation_lines: list[str]
    risks_title: str
    risks: list[str]
    metadata_title: str
    metadata_fields: list[ExportField]
    page_label: str
    empty_risks_text: str


def _register_pdf_font() -> None:
    if _PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(_PDF_FONT_NAME))


def normalize_export_formats(formats: list[str] | tuple[str, ...] | None) -> list[str]:
    ordered_formats: list[str] = []
    seen: set[str] = set()
    for raw_value in formats or ["pdf"]:
        candidate = str(raw_value or "").strip().lower()
        if candidate not in SUPPORTED_EXPORT_FORMATS or candidate in seen:
            continue
        seen.add(candidate)
        ordered_formats.append(candidate)
    return ordered_formats or ["pdf"]


def _build_file_url(settings: Settings, filename: str) -> str:
    return urljoin(f"{settings.public_api_url.rstrip('/')}/", f"{settings.api_prefix.strip('/')}/{EXPORT_FILES_ROUTE.strip('/')}/{quote(filename)}")


def _resolve_export_path(settings: Settings, filename: str) -> Path:
    export_root = settings.resolved_export_root.resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    path = (export_root / filename).resolve()
    try:
        path.relative_to(export_root)
    except ValueError as exc:
        raise ValueError("Export path escapes export root") from exc
    return path


def resolve_export_file_path(settings: Settings, filename: str) -> Path:
    normalized = str(filename or "").strip()
    if not normalized or ":" in normalized or "/" in normalized or "\\" in normalized or Path(normalized).name != normalized:
        raise ValueError("Invalid export filename")
    return _resolve_export_path(settings, normalized)


def _build_export_labels(zh_output: bool) -> dict[str, str]:
    if zh_output:
        return {
            "booking_title": "\u9884\u8ba2\u4e0e\u9884\u7ea6",
            "transport_booking_title": "\u4ea4\u901a\u9884\u8ba2\u6458\u8981",
            "reservation_lines_title": "\u666f\u70b9\u9884\u7ea6\u6e05\u5355",
            "recommended_option": "\u63a8\u8350\u65b9\u6848",
            "intercity_estimate": "\u8de8\u57ce\u4ea4\u901a\u4f30\u7b97",
            "local_transport_estimate": "\u672c\u5730\u4ea4\u901a\u4f30\u7b97",
            "booking_window": "\u9884\u8ba2\u7a97\u53e3",
            "advance_booking": "\u63d0\u524d\u9884\u8ba2",
            "booking_url": "\u9884\u8ba2\u94fe\u63a5",
            "handbook_label": "旅行手册 PDF",
            "summary_title": "总体摘要",
            "basics_title": "行程基础信息",
            "overview_title": "行程概览",
            "itinerary_title": "逐日行程",
            "budget_title": "预算总结",
            "risks_title": "风险与注意事项",
            "metadata_title": "导出信息",
            "page_label": "第",
            "destination": "目的地",
            "dates": "日期",
            "budget": "预算上限",
            "travelers": "出行人数",
            "pace": "节奏",
            "transport": "交通方式",
            "stay": "住宿偏好",
            "interests": "兴趣偏好",
            "days": "总天数",
            "stops": "总条目数",
            "estimate": "预计总花费",
            "budget_status": "预算状态",
            "risk_count": "风险数量",
            "day_cost": "当日预算",
            "weather": "天气提示",
            "weather_notes": "天气备注",
            "item_type": "活动类型",
            "location": "地点",
            "score": "推荐分",
            "item_cost": "费用估算",
            "requested_budget": "预算上限",
            "estimated_total": "预计总花费",
            "remaining_budget": "剩余预算",
            "over_budget": "超支金额",
            "tickets": "门票",
            "dining": "餐饮",
            "accommodation": "住宿",
            "transport_breakdown": "交通",
            "other": "其他",
            "budget_lines": "预算明细",
            "exported_at": "导出时间",
            "job_id": "导出任务 ID",
            "provider": "生成链路",
            "file_url": "文件地址",
            "status_under": "预算充足",
            "status_near": "预算接近上限",
            "status_over": "预算超支",
            "not_available": "暂无",
            "none": "暂无",
        }
    return {
        "booking_title": "Booking And Reservations",
        "transport_booking_title": "Transport Booking Summary",
        "reservation_lines_title": "Attraction Booking Checklist",
        "recommended_option": "Recommended Option",
        "intercity_estimate": "Intercity Estimate",
        "local_transport_estimate": "Local Estimate",
        "booking_window": "Booking Window",
        "advance_booking": "Advance Booking",
        "booking_url": "Booking URL",
        "handbook_label": "Travel Handbook PDF",
        "summary_title": "Summary",
        "basics_title": "Trip Basics",
        "overview_title": "Overview",
        "itinerary_title": "Daily Itinerary",
        "budget_title": "Budget Summary",
        "risks_title": "Risks And Notes",
        "metadata_title": "Export Metadata",
        "page_label": "Page",
        "destination": "Destination",
        "dates": "Dates",
        "budget": "Budget Cap",
        "travelers": "Travelers",
        "pace": "Pace",
        "transport": "Transport",
        "stay": "Stay Preference",
        "interests": "Interests",
        "days": "Total Days",
        "stops": "Planned Stops",
        "estimate": "Estimated Spend",
        "budget_status": "Budget Status",
        "risk_count": "Risk Count",
        "day_cost": "Day Budget",
        "weather": "Weather",
        "weather_notes": "Weather Notes",
        "item_type": "Activity Type",
        "location": "Location",
        "score": "Score",
        "item_cost": "Estimated Cost",
        "requested_budget": "Requested Budget",
        "estimated_total": "Estimated Total",
        "remaining_budget": "Remaining Budget",
        "over_budget": "Over Budget",
        "tickets": "Tickets",
        "dining": "Dining",
        "accommodation": "Accommodation",
        "transport_breakdown": "Transport",
        "other": "Other",
        "budget_lines": "Budget Lines",
        "exported_at": "Exported At",
        "job_id": "Export Job ID",
        "provider": "Pipeline",
        "file_url": "File URL",
        "status_under": "Under budget",
        "status_near": "Near budget cap",
        "status_over": "Over budget",
        "not_available": "N/A",
        "none": "None",
    }


def _format_budget_status(status: str, labels: dict[str, str]) -> str:
    mapping = {
        "under": labels["status_under"],
        "near": labels["status_near"],
        "over": labels["status_over"],
    }
    return mapping.get(status, status or labels["not_available"])


def _format_currency(value: float, zh_output: bool) -> str:
    return f"CNY {value:,.2f}" if zh_output else f"CNY {value:,.2f}"


def _format_date_range(request: PlanningRequest) -> str:
    return f"{request.start_date.isoformat()} - {request.end_date.isoformat()}"


def _format_interests(interests: list[str], labels: dict[str, str]) -> str:
    values = [item.strip() for item in interests if item and item.strip()]
    return ", ".join(values) if values else labels["not_available"]


def _normalize_text(value: str | None, labels: dict[str, str]) -> str:
    normalized = str(value or "").strip()
    return normalized or labels["not_available"]


def _estimate_item_costs(day: PlannedDay) -> list[float]:
    if not day.items:
        return []
    total_cost = max(day.total_cost, 0.0)
    if total_cost <= 0:
        return [0.0 for _ in day.items]

    weights = [_ITEM_COST_WEIGHTS.get((item.type or "").strip().lower(), 1.0) for item in day.items]
    weight_total = sum(weights) or float(len(day.items))
    raw_amounts = [total_cost * weight / weight_total for weight in weights]
    rounded_amounts = [round(amount, 2) for amount in raw_amounts]
    diff = round(total_cost - sum(rounded_amounts), 2)
    if diff:
        dominant_index = max(range(len(raw_amounts)), key=lambda index: raw_amounts[index])
        rounded_amounts[dominant_index] = round(rounded_amounts[dominant_index] + diff, 2)
    return rounded_amounts


def _ensure_budget_summary(plan: PlanningResult, request: PlanningRequest) -> PlanningResult:
    return enrich_plan_with_budget(plan, request)


def _build_transport_booking_fields(plan: PlanningResult, labels: dict[str, str], zh_output: bool) -> list[ExportField]:
    summary = plan.transport_booking_summary
    if summary is None:
        return []
    return [
        ExportField(labels["recommended_option"], _normalize_text(summary.recommended_option, labels)),
        ExportField(labels["intercity_estimate"], _format_currency(summary.estimated_intercity_cost, zh_output)),
        ExportField(labels["local_transport_estimate"], _format_currency(summary.estimated_local_transport_cost, zh_output)),
        ExportField(labels["booking_window"], _normalize_text(summary.booking_window, labels)),
        ExportField(labels["booking_url"], _normalize_text(summary.official_booking_url, labels)),
        ExportField(
            labels["advance_booking"],
            ("\u5efa\u8bae\u63d0\u524d\u9884\u8ba2" if zh_output else "Recommended") if summary.booking_required else ("\u6309\u9700" if zh_output else "As needed"),
        ),
    ]


def _build_reservation_lines(plan: PlanningResult, labels: dict[str, str], zh_output: bool) -> list[str]:
    lines: list[str] = []
    for day in plan.days:
        for item in day.items:
            notes: list[str] = []
            if item.booking_info is not None:
                if item.booking_info.price_label:
                    notes.append(f"{labels['tickets']}: {item.booking_info.price_label}")
                if item.booking_info.booking_window:
                    notes.append(f"{labels['booking_window']}: {item.booking_info.booking_window}")
                if item.booking_info.official_booking_url:
                    notes.append(f"{labels['booking_url']}: {item.booking_info.official_booking_url}")
                if item.booking_info.reminder:
                    notes.append(item.booking_info.reminder)
            if item.visit_requirements is not None:
                if item.visit_requirements.reservation_policy:
                    notes.append(f"{labels['advance_booking']}: {item.visit_requirements.reservation_policy}")
                if item.visit_requirements.advance_booking_note:
                    notes.append(item.visit_requirements.advance_booking_note)
            if not notes:
                continue
            prefix = f"\u7b2c {day.day_index} \u5929" if zh_output else f"Day {day.day_index}"
            lines.append(f"{prefix} | {item.name}: {'; '.join(notes)}")
    return lines


def _build_day_view(day: PlannedDay, labels: dict[str, str], zh_output: bool) -> ExportDayView:
    item_costs = _estimate_item_costs(day)
    items: list[ExportItemView] = []

    for index, item in enumerate(day.items):
        details = [
            f"{labels['location']}: {_normalize_text(item.location, labels)}",
            f"{labels['score']}: {item.score:.2f}",
            _normalize_text(item.note, labels),
        ]
        if item.booking_info is not None:
            if item.booking_info.price_label:
                details.append(f"{labels['tickets']}: {item.booking_info.price_label}")
            if item.booking_info.estimated_price is not None and item.booking_info.estimated_price > 0:
                details.append(f"{labels['item_cost']}: {_format_currency(item.booking_info.estimated_price, zh_output)}")
            if item.booking_info.booking_window:
                details.append(f"{labels['booking_window']}: {item.booking_info.booking_window}")
            if item.booking_info.official_booking_url:
                details.append(f"{labels['booking_url']}: {item.booking_info.official_booking_url}")
            if item.booking_info.reminder:
                details.append(item.booking_info.reminder)
            for note in item.booking_info.notes:
                normalized_note = note.strip()
                if normalized_note:
                    details.append(normalized_note)
        if item.visit_requirements is not None:
            if item.visit_requirements.reservation_policy:
                details.append(f"{labels['advance_booking']}: {item.visit_requirements.reservation_policy}")
            if item.visit_requirements.advance_booking_note:
                details.append(item.visit_requirements.advance_booking_note)
            if item.visit_requirements.timed_entry:
                details.append("Timed entry applies" if not zh_output else "\u5305\u542b\u5206\u65f6\u5165\u573a\u8981\u6c42")
            if item.visit_requirements.identity_required:
                details.append("Identity or name check may apply" if not zh_output else "\u53ef\u80fd\u9700\u8981\u5b9e\u540d\u6216\u8bc1\u4ef6\u6821\u9a8c")
            for note in item.visit_requirements.notes:
                normalized_note = note.strip()
                if normalized_note:
                    details.append(normalized_note)
        if item.route_from_previous is not None:
            details.append(item.route_from_previous.summary)
        if item.location_ref is not None and item.location_ref.summary:
            details.append(item.location_ref.summary)

        items.append(
            ExportItemView(
                time_range=f"{item.start_time} - {item.end_time}",
                title=_normalize_text(item.name, labels),
                meta=f"{labels['item_type']}: {_normalize_text(item.type, labels)}",
                estimated_cost=f"{labels['item_cost']}: {_format_currency(item_costs[index], zh_output)}",
                details=details,
            )
        )

    facts = [f"{labels['day_cost']}: {_format_currency(day.total_cost, zh_output)}"]
    if day.weather is not None and day.weather.summary.strip():
        facts.append(f"{labels['weather']}: {day.weather.summary.strip()}")
    if day.weather is not None:
        for note in day.weather.notes:
            normalized = note.strip()
            if normalized:
                facts.append(f"{labels['weather_notes']}: {normalized}")

    return ExportDayView(
        heading=f"Day {day.day_index} | {day.title}" if not zh_output else f"第 {day.day_index} 天 | {day.title}",
        summary=_normalize_text(day.summary, labels),
        facts=facts,
        items=items,
    )


def _build_export_document(
    *,
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    exported_at: datetime,
    file_url: str,
) -> ExportDocumentView:
    zh_output = is_chinese_output(request)
    labels = _build_export_labels(zh_output)
    enriched_plan = _ensure_budget_summary(plan, request)
    budget_summary = enriched_plan.budget_summary
    assert budget_summary is not None

    total_stops = sum(len(day.items) for day in enriched_plan.days)
    basic_fields = [
        ExportField(labels["destination"], _normalize_text(request.destination, labels)),
        ExportField(labels["dates"], _format_date_range(request)),
        ExportField(labels["budget"], _format_currency(request.budget, zh_output)),
        ExportField(labels["travelers"], str(request.travelers)),
        ExportField(labels["pace"], _normalize_text(request.pace, labels)),
        ExportField(labels["transport"], _normalize_text(request.transport_mode, labels)),
        ExportField(labels["stay"], _normalize_text(request.accommodation_preference, labels)),
        ExportField(labels["interests"], _format_interests(request.interests, labels)),
    ]
    overview_fields = [
        ExportField(labels["days"], str(len(enriched_plan.days))),
        ExportField(labels["stops"], str(total_stops)),
        ExportField(labels["estimate"], _format_currency(enriched_plan.total_budget_estimate, zh_output)),
        ExportField(labels["budget_status"], _format_budget_status(budget_summary.status, labels)),
        ExportField(labels["risk_count"], str(len(enriched_plan.risks))),
    ]
    budget_fields = [
        ExportField(labels["requested_budget"], _format_currency(budget_summary.requested_budget, zh_output)),
        ExportField(labels["estimated_total"], _format_currency(budget_summary.estimated_total, zh_output)),
        ExportField(
            labels["over_budget"] if budget_summary.over_budget > 0 else labels["remaining_budget"],
            _format_currency(
                budget_summary.over_budget if budget_summary.over_budget > 0 else budget_summary.remaining_budget,
                zh_output,
            ),
        ),
        ExportField(labels["budget_status"], _format_budget_status(budget_summary.status, labels)),
    ]
    budget_breakdown_fields = [
        ExportField(labels["tickets"], _format_currency(budget_summary.breakdown.tickets, zh_output)),
        ExportField(labels["dining"], _format_currency(budget_summary.breakdown.dining, zh_output)),
        ExportField(labels["accommodation"], _format_currency(budget_summary.breakdown.accommodation, zh_output)),
        ExportField(labels["transport_breakdown"], _format_currency(budget_summary.breakdown.transport, zh_output)),
        ExportField(labels["other"], _format_currency(budget_summary.breakdown.other, zh_output)),
    ]
    budget_lines = [
        ExportBudgetLineView(
            title=_normalize_text(item.title, labels),
            amount=_format_currency(item.amount, zh_output),
            note=item.note.strip() if item.note else None,
        )
        for item in budget_summary.line_items
    ]
    transport_booking_fields = _build_transport_booking_fields(enriched_plan, labels, zh_output)
    reservation_lines = _build_reservation_lines(enriched_plan, labels, zh_output)
    metadata_fields = [
        ExportField(labels["exported_at"], exported_at.isoformat(timespec="seconds")),
        ExportField(labels["job_id"], job_id),
        ExportField(labels["provider"], _normalize_text(getattr(enriched_plan.trace, "provider", None), labels)),
        ExportField(labels["file_url"], file_url),
    ]

    title = _normalize_text(draft.title or request.title or request.destination, labels)
    subtitle = _normalize_text(draft.subtitle, labels)
    if subtitle == labels["not_available"]:
        subtitle = _format_date_range(request)

    return ExportDocumentView(
        title=title,
        subtitle=subtitle,
        handbook_label=labels["handbook_label"],
        summary_title=labels["summary_title"],
        summary_text=_normalize_text(enriched_plan.summary, labels),
        basics_title=labels["basics_title"],
        basic_fields=basic_fields,
        overview_title=labels["overview_title"],
        overview_fields=overview_fields,
        itinerary_title=labels["itinerary_title"],
        days=[_build_day_view(day, labels, zh_output) for day in enriched_plan.days],
        budget_title=labels["budget_title"],
        budget_fields=budget_fields,
        budget_breakdown_fields=budget_breakdown_fields,
        budget_lines_title=labels["budget_lines"],
        budget_lines=budget_lines,
        booking_title=labels["booking_title"],
        transport_booking_title=labels["transport_booking_title"],
        transport_booking_fields=transport_booking_fields,
        reservation_lines_title=labels["reservation_lines_title"],
        reservation_lines=reservation_lines,
        risks_title=labels["risks_title"],
        risks=[risk.strip() for risk in enriched_plan.risks if risk and risk.strip()],
        metadata_title=labels["metadata_title"],
        metadata_fields=metadata_fields,
        page_label=labels["page_label"],
        empty_risks_text=labels["none"],
    )


def _build_styles() -> dict[str, ParagraphStyle]:
    stylesheet = getSampleStyleSheet()
    base = ParagraphStyle(
        "ExportBase",
        parent=stylesheet["Normal"],
        fontName=_PDF_FONT_NAME,
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#1F2A30"),
        wordWrap="CJK",
    )
    return {
        "base": base,
        "small": ParagraphStyle("ExportSmall", parent=base, fontSize=9, leading=12, textColor=_MUTED_TEXT),
        "badge": ParagraphStyle(
            "ExportBadge",
            parent=base,
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.white,
            spaceAfter=3 * mm,
        ),
        "title": ParagraphStyle(
            "ExportTitle",
            parent=base,
            fontSize=24,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#162126"),
            spaceAfter=2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "ExportSubtitle",
            parent=base,
            fontSize=11.5,
            leading=16,
            alignment=TA_CENTER,
            textColor=_MUTED_TEXT,
            spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "ExportSection",
            parent=base,
            fontSize=15,
            leading=20,
            textColor=_ACCENT_COLOR,
            spaceAfter=2.5 * mm,
            keepWithNext=True,
        ),
        "card_title": ParagraphStyle(
            "ExportCardTitle",
            parent=base,
            fontSize=12.5,
            leading=17,
            textColor=colors.HexColor("#162126"),
            spaceAfter=1.2 * mm,
        ),
        "day_title": ParagraphStyle(
            "ExportDayTitle",
            parent=base,
            fontSize=13.5,
            leading=18,
            textColor=colors.HexColor("#162126"),
            spaceAfter=1.2 * mm,
            keepWithNext=True,
        ),
        "item_title": ParagraphStyle(
            "ExportItemTitle",
            parent=base,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#162126"),
            spaceAfter=1 * mm,
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _build_field_table(fields: list[ExportField], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [[_paragraph(field.label, styles["small"]), _paragraph(field.value, styles["base"])] for field in fields]
    table = Table(rows, colWidths=[38 * mm, None], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _CARD_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, _BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _build_cover_card(view: ExportDocumentView, styles: dict[str, ParagraphStyle]) -> Table:
    badge = Table([[_paragraph(view.handbook_label, styles["badge"])]], colWidths=[None], hAlign="CENTER")
    badge.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _ACCENT_COLOR),
                ("BOX", (0, 0), (-1, -1), 0, colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    cover = Table(
        [
            [badge],
            [_paragraph(view.title, styles["title"])],
            [_paragraph(view.subtitle, styles["subtitle"])],
            [_paragraph(view.summary_text, styles["base"])],
        ],
        colWidths=[None],
        hAlign="CENTER",
    )
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3EFE7")),
                ("BOX", (0, 0), (-1, -1), 0.8, _BORDER_COLOR),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return cover


def _build_item_table(item: ExportItemView, styles: dict[str, ParagraphStyle]) -> Table:
    right_column = [
        _paragraph(item.title, styles["item_title"]),
        _paragraph(item.meta, styles["small"]),
        _paragraph(item.estimated_cost, styles["small"]),
    ]
    right_column.extend(_paragraph(detail, styles["base"]) for detail in item.details)
    table = Table(
        [
            [
                _paragraph(item.time_range, styles["small"]),
                Table([[line] for line in right_column], colWidths=[None], hAlign="LEFT"),
            ]
        ],
        colWidths=[28 * mm, None],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _build_budget_lines_table(lines: list[ExportBudgetLineView], styles: dict[str, ParagraphStyle]) -> Table:
    rows = []
    for line in lines:
        title = escape(line.title)
        if line.note:
            title = f"{title}<br/>{escape(line.note)}"
        rows.append([Paragraph(title, styles["base"]), _paragraph(line.amount, styles["base"])])
    table = Table(rows, colWidths=[None, 36 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, _BORDER_COLOR),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, _BORDER_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _draw_page_frame(canvas, doc, *, view: ExportDocumentView) -> None:
    canvas.saveState()
    canvas.setTitle(view.title)
    canvas.setAuthor("TravelMind AI")
    canvas.setSubject(view.subtitle)
    canvas.setCreator("TravelMind AI export service")
    canvas.setStrokeColor(_BORDER_COLOR)
    canvas.line(doc.leftMargin, 18 * mm, _PAGE_WIDTH - doc.rightMargin, 18 * mm)
    canvas.setFont(_PDF_FONT_NAME, 8)
    canvas.setFillColor(_MUTED_TEXT)
    canvas.drawString(doc.leftMargin, 12 * mm, view.title[:64])
    canvas.drawRightString(
        _PAGE_WIDTH - doc.rightMargin,
        12 * mm,
        f"{view.page_label} {canvas.getPageNumber()}",
    )
    canvas.restoreState()


def _render_pdf(view: ExportDocumentView) -> bytes:
    _register_pdf_font()
    styles = _build_styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=24 * mm,
        title=view.title,
        author="TravelMind AI",
        subject=view.subtitle,
        creator="TravelMind AI export service",
        pageCompression=0,
    )

    story = [
        _build_cover_card(view, styles),
        Spacer(1, _SECTION_GAP),
        _paragraph(view.basics_title, styles["section"]),
        _build_field_table(view.basic_fields, styles),
        Spacer(1, _SECTION_GAP),
        _paragraph(view.overview_title, styles["section"]),
        _build_field_table(view.overview_fields, styles),
        Spacer(1, _SECTION_GAP),
        _paragraph(view.summary_title, styles["section"]),
        _paragraph(view.summary_text, styles["base"]),
        PageBreak(),
        _paragraph(view.itinerary_title, styles["section"]),
    ]

    for day in view.days:
        story.append(_paragraph(day.heading, styles["day_title"]))
        story.append(_paragraph(day.summary, styles["base"]))
        for fact in day.facts:
            story.append(_paragraph(fact, styles["small"]))
        story.append(Spacer(1, 2 * mm))
        for item in day.items:
            story.append(_build_item_table(item, styles))
            story.append(Spacer(1, 2.5 * mm))
        story.append(Spacer(1, _SECTION_GAP))

    story.extend(
        [
            _paragraph(view.budget_title, styles["section"]),
            _build_field_table(view.budget_fields, styles),
            Spacer(1, 3 * mm),
            _build_field_table(view.budget_breakdown_fields, styles),
        ]
    )
    if view.budget_lines:
        story.extend(
            [
                Spacer(1, 3 * mm),
                _paragraph(view.budget_lines_title, styles["card_title"]),
                _build_budget_lines_table(view.budget_lines, styles),
            ]
        )

    if view.transport_booking_fields or view.reservation_lines:
        story.extend([Spacer(1, _SECTION_GAP), _paragraph(view.booking_title, styles["section"])])
        if view.transport_booking_fields:
            story.extend(
                [
                    _paragraph(view.transport_booking_title, styles["card_title"]),
                    _build_field_table(view.transport_booking_fields, styles),
                ]
            )
        if view.reservation_lines:
            story.extend([Spacer(1, 3 * mm), _paragraph(view.reservation_lines_title, styles["card_title"])])
            for line in view.reservation_lines:
                story.append(_paragraph(f"- {line}", styles["base"]))

    story.extend([Spacer(1, _SECTION_GAP), _paragraph(view.risks_title, styles["section"])])
    if view.risks:
        for risk in view.risks:
            story.append(_paragraph(f"- {risk}", styles["base"]))
    else:
        story.append(_paragraph(f"- {view.empty_risks_text}", styles["base"]))

    story.extend(
        [
            Spacer(1, _SECTION_GAP),
            _paragraph(view.metadata_title, styles["section"]),
            _build_field_table(view.metadata_fields, styles),
        ]
    )

    document.build(
        story,
        onFirstPage=lambda canvas, doc: _draw_page_frame(canvas, doc, view=view),
        onLaterPages=lambda canvas, doc: _draw_page_frame(canvas, doc, view=view),
    )
    return buffer.getvalue()


def _render_markdown(view: ExportDocumentView) -> bytes:
    lines = [
        f"# {view.title}",
        "",
        view.subtitle,
        "",
        f"_{view.handbook_label}_",
        "",
        f"## {view.summary_title}",
        "",
        view.summary_text,
        "",
        f"## {view.basics_title}",
        "",
    ]
    for field in view.basic_fields:
        lines.append(f"- {field.label}: {field.value}")

    lines.extend(["", f"## {view.overview_title}", ""])
    for field in view.overview_fields:
        lines.append(f"- {field.label}: {field.value}")

    lines.extend(["", f"## {view.itinerary_title}", ""])
    for day in view.days:
        lines.extend([f"### {day.heading}", "", day.summary, ""])
        for fact in day.facts:
            lines.append(f"- {fact}")
        if day.facts:
            lines.append("")
        for item in day.items:
            lines.extend([f"#### {item.time_range} {item.title}", f"- {item.meta}", f"- {item.estimated_cost}"])
            for detail in item.details:
                lines.append(f"- {detail}")
            lines.append("")

    lines.extend(["", f"## {view.budget_title}", ""])
    for field in view.budget_fields:
        lines.append(f"- {field.label}: {field.value}")

    lines.extend(["", f"### {_build_markdown_breakdown_heading(view)}", ""])
    for field in view.budget_breakdown_fields:
        lines.append(f"- {field.label}: {field.value}")

    if view.budget_lines:
        lines.extend(["", f"### {view.budget_lines_title}", ""])
        for line in view.budget_lines:
            label = f"- {line.title}: {line.amount}"
            if line.note:
                label = f"{label} ({line.note})"
            lines.append(label)

    if view.transport_booking_fields or view.reservation_lines:
        lines.extend(["", f"## {view.booking_title}", ""])
        if view.transport_booking_fields:
            lines.extend([f"### {view.transport_booking_title}", ""])
            for field in view.transport_booking_fields:
                lines.append(f"- {field.label}: {field.value}")
        if view.reservation_lines:
            lines.extend(["", f"### {view.reservation_lines_title}", ""])
            for line in view.reservation_lines:
                lines.append(f"- {line}")

    lines.extend(["", f"## {view.risks_title}", ""])
    if view.risks:
        for risk in view.risks:
            lines.append(f"- {risk}")
    else:
        lines.append(f"- {view.empty_risks_text}")

    lines.extend(["", f"## {view.metadata_title}", ""])
    for field in view.metadata_fields:
        lines.append(f"- {field.label}: {field.value}")

    return ("\n".join(lines).strip() + "\n").encode("utf-8")


def _render_export_json(
    *,
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    exported_at: datetime,
    formats: list[str],
) -> bytes:
    payload = {
        "manifest_version": 1,
        "exported_at": exported_at.isoformat(),
        "job_id": job_id,
        "formats": formats,
        "trip_request": request.model_dump(mode="json"),
        "itinerary": plan.model_dump(mode="json"),
        "export_draft": draft.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _persist_export_bytes(
    *,
    artifact_type: str,
    filename: str,
    content_type: str,
    payload: bytes,
    settings: Settings,
) -> dict[str, Any]:
    path = _resolve_export_path(settings, filename)
    file_url = _build_file_url(settings, filename)
    Path(path).write_bytes(payload)
    return {
        "type": artifact_type,
        "file_name": filename,
        "file_path": str(path),
        "file_url": file_url,
        "content_type": content_type,
        "size_bytes": len(payload),
    }


def _build_artifact_manifest(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    primary_artifact = next((artifact for artifact in artifacts if artifact.get("type") == "pdf"), artifacts[0] if artifacts else None)
    result: dict[str, Any] = {
        "manifest_version": 1,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "primary_artifact": primary_artifact.get("type") if primary_artifact else None,
    }
    if primary_artifact is not None:
        for key in ("file_name", "file_path", "file_url", "content_type", "size_bytes"):
            result[key] = primary_artifact.get(key)
    return result


def _build_markdown_breakdown_heading(view: ExportDocumentView) -> str:
    return "Budget Breakdown" if view.page_label == "Page" else "预算拆分"


def write_pdf_export(
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    settings: Settings,
    *,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    filename = f"{job_id}.pdf"
    file_url = _build_file_url(settings, filename)
    timestamp = exported_at or datetime.now(timezone.utc)
    document_view = _build_export_document(
        job_id=job_id,
        request=request,
        plan=plan,
        draft=draft,
        exported_at=timestamp,
        file_url=file_url,
    )
    payload = _render_pdf(document_view)
    return _persist_export_bytes(
        artifact_type="pdf",
        filename=filename,
        content_type="application/pdf",
        payload=payload,
        settings=settings,
    )


def write_markdown_export(
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    settings: Settings,
    *,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    filename = f"{job_id}.md"
    file_url = _build_file_url(settings, filename)
    document_view = _build_export_document(
        job_id=job_id,
        request=request,
        plan=plan,
        draft=draft,
        exported_at=exported_at or datetime.now(timezone.utc),
        file_url=file_url,
    )
    payload = _render_markdown(document_view)
    return _persist_export_bytes(
        artifact_type="md",
        filename=filename,
        content_type="text/markdown; charset=utf-8",
        payload=payload,
        settings=settings,
    )


def write_json_export(
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    settings: Settings,
    *,
    exported_at: datetime | None = None,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    timestamp = exported_at or datetime.now(timezone.utc)
    payload = _render_export_json(
        job_id=job_id,
        request=request,
        plan=plan,
        draft=draft,
        exported_at=timestamp,
        formats=normalize_export_formats(formats),
    )
    return _persist_export_bytes(
        artifact_type="json",
        filename=f"{job_id}.json",
        content_type="application/json",
        payload=payload,
        settings=settings,
    )


def write_export_bundle(
    job_id: str,
    request: PlanningRequest,
    plan: PlanningResult,
    draft: ExportDraft,
    settings: Settings,
    *,
    formats: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    normalized_formats = normalize_export_formats(list(formats) if formats is not None else None)
    exported_at = datetime.now(timezone.utc)
    artifacts: list[dict[str, Any]] = []
    for export_format in normalized_formats:
        if export_format == "md":
            artifacts.append(write_markdown_export(job_id, request, plan, draft, settings, exported_at=exported_at))
        elif export_format == "pdf":
            artifacts.append(write_pdf_export(job_id, request, plan, draft, settings, exported_at=exported_at))
        elif export_format == "json":
            artifacts.append(write_json_export(job_id, request, plan, draft, settings, exported_at=exported_at, formats=normalized_formats))
    return _build_artifact_manifest(artifacts)

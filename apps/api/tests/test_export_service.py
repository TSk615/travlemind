import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from travelmind_api.agents.base import (
    AgentTrace,
    BookingInfo,
    ExportDraft,
    PlannedDay,
    PlannedDayWeather,
    PlannedItem,
    PlanningRequest,
    PlanningResult,
    TransportBookingSummary,
    VisitRequirements,
)
from travelmind_api.core.config import Settings
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.export_service import _build_export_document, write_export_bundle, write_pdf_export


def _build_request() -> PlanningRequest:
    return PlanningRequest(
        trip_id="trip_pdf_test",
        title="京都慢行手册",
        origin="上海",
        destination="京都",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        budget=5200,
        travelers=2,
        interests=["寺庙", "咖啡", "慢逛"],
        accommodation_preference="安静町屋旅馆",
        pace="balanced",
        transport_mode="rail",
        locale="zh-CN",
    )


def _build_plan(request: PlanningRequest) -> PlanningResult:
    days = [
        PlannedDay(
            day_index=1,
            title="东山慢游",
            summary="早段安排寺庙与街巷步行，午后留给咖啡馆和轻量拍照。",
            total_cost=1600,
            weather=PlannedDayWeather(
                summary="上午晴，傍晚转凉。",
                notes=["带一件轻薄外套。", "热门寺庙建议 09:00 前到达。"],
            ),
            items=[
                PlannedItem(
                    id="item_1_1",
                    type="sight",
                    name="清水寺",
                    start_time="08:30",
                    end_time="10:30",
                    location="京都东山区",
                    score=0.93,
                    note="把核心景点放在早段，避开中午人流。",
                ),
                PlannedItem(
                    id="item_1_2",
                    type="meal",
                    name="二年坂咖啡馆",
                    start_time="11:00",
                    end_time="12:30",
                    location="二年坂",
                    score=0.84,
                    note="中午用餐和休息，保持节奏平稳。",
                ),
                PlannedItem(
                    id="item_1_3",
                    type="explore",
                    name="祗园散步",
                    start_time="14:00",
                    end_time="17:00",
                    location="祗园",
                    score=0.82,
                    note="傍晚前完成街区漫步，保留机动时间。",
                ),
            ],
        ),
        PlannedDay(
            day_index=2,
            title="市区美食与市场",
            summary="用市场与小店组合中段节奏，避免全天跨城转移。",
            total_cost=1700,
            weather=PlannedDayWeather(
                summary="中午后可能有短时阵雨。",
                notes=["备一把折叠伞。"],
            ),
            items=[
                PlannedItem(
                    id="item_2_1",
                    type="food",
                    name="锦市场早午餐",
                    start_time="09:30",
                    end_time="11:30",
                    location="锦市场",
                    score=0.88,
                    note="把高密度餐饮安排在同一区域，减少移动成本。",
                ),
                PlannedItem(
                    id="item_2_2",
                    type="photo",
                    name="鸭川河畔拍照",
                    start_time="13:00",
                    end_time="14:30",
                    location="鸭川",
                    score=0.8,
                    note="雨势变大时可缩短停留时间。",
                ),
                PlannedItem(
                    id="item_2_3",
                    type="meal",
                    name="先斗町晚餐",
                    start_time="18:00",
                    end_time="20:00",
                    location="先斗町",
                    score=0.86,
                    note="收尾安排在步行友好区域，方便返程。",
                ),
            ],
        ),
        PlannedDay(
            day_index=3,
            title="岚山收尾",
            summary="最后一天控制条目数量，优先自然景观和轻量步行。",
            total_cost=1550,
            weather=PlannedDayWeather(
                summary="全天温和，早间舒适。",
                notes=["竹林区域清晨体感最好。"],
            ),
            items=[
                PlannedItem(
                    id="item_3_1",
                    type="sight",
                    name="岚山竹林",
                    start_time="08:00",
                    end_time="09:30",
                    location="岚山",
                    score=0.9,
                    note="尽量提早入场，避免旅行团高峰。",
                ),
                PlannedItem(
                    id="item_3_2",
                    type="explore",
                    name="渡月桥周边散步",
                    start_time="10:00",
                    end_time="11:30",
                    location="渡月桥",
                    score=0.79,
                    note="用轻量步行收尾，降低返程前疲劳。",
                ),
                PlannedItem(
                    id="item_3_3",
                    type="meal",
                    name="河畔午餐",
                    start_time="12:00",
                    end_time="13:30",
                    location="岚山站附近",
                    score=0.81,
                    note="午餐后预留整理行李和返程时间。",
                ),
            ],
        ),
    ]

    days[0].items[0].booking_info = BookingInfo(
        price_label="Adult ticket around 500 JPY",
        estimated_price=25,
        official_booking_url="https://www.kiyomizudera.or.jp/en/visit",
        booking_window="Buy on the day unless seasonal controls change.",
        notes=["Use the official page for current seasonal notices."],
    )
    days[0].items[0].visit_requirements = VisitRequirements(
        reservation_policy="not_needed",
        advance_booking_note="Peak foliage periods may introduce timed-entry controls.",
    )

    plan = PlanningResult(
        summary="三天行程围绕慢节奏寺庙、街区散步和稳定预算展开，整体适合第一次到京都的双人出行。",
        total_budget_estimate=4850,
        days=days,
        risks=["热门寺庙需要提早到达。", "第二天下午短时阵雨可能影响河边停留。"],
        transport_booking_summary=TransportBookingSummary(
            recommended_option="Kyoto rail arrival and subway-first local movement",
            estimated_intercity_cost=760,
            estimated_local_transport_cost=180,
            booking_required=True,
            official_booking_url="https://rail.example.test/kyoto",
            booking_window="Reserve early during peak periods",
            pass_or_ticket_notes=["Point-to-point tickets are enough for this version."],
            reminders=["Reserve seats ahead of peak departures."],
        ),
        trace=AgentTrace(
            provider="stub",
            workflow_id="wf_pdf_test",
            notes=["Generated for PDF export tests."],
        ),
    )
    return enrich_plan_with_budget(plan, request)


def test_build_export_document_maps_trip_structure_into_sections():
    request = _build_request()
    plan = _build_plan(request)
    draft = ExportDraft(title=request.title, subtitle="京都 3 天游览手册", sections=["unused"])

    view = _build_export_document(
        job_id="job_pdf_test",
        request=request,
        plan=plan,
        draft=draft,
        exported_at=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        file_url="http://testserver/exports/files/job_pdf_test.pdf",
    )

    assert view.title == "京都慢行手册"
    assert any(field.label == "目的地" and field.value == "京都" for field in view.basic_fields)
    assert any(field.label == "总天数" and field.value == "3" for field in view.overview_fields)
    assert len(view.days) == 3
    assert view.days[0].items[0].estimated_cost.startswith("费用估算")
    assert any("天气提示" in fact for fact in view.days[0].facts)
    assert view.budget_lines
    assert view.transport_booking_fields
    assert view.reservation_lines
    assert any("500 JPY" in line for line in view.reservation_lines)
    assert view.budget_lines[0].title.startswith("第 1 天")
    assert "热门寺庙需要提早到达。" in view.risks
    assert "第二天下午短时阵雨可能影响河边停留。" in view.risks
    assert any("预算上限" in risk or "预算" in risk for risk in view.risks)
    assert any(field.label == "生成链路" and field.value == "stub" for field in view.metadata_fields)


def test_write_pdf_export_generates_multi_page_pdf_with_cjk_font():
    request = _build_request()
    plan = _build_plan(request)
    draft = ExportDraft(title=request.title, subtitle="京都 3 天游览手册", sections=[])
    export_root = Path("storage/.pytest_tmp/export-service") / uuid.uuid4().hex
    export_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(export_root=str(export_root), public_api_url="http://testserver")

    try:
        result = write_pdf_export("job_pdf_test", request, plan, draft, settings)

        pdf_path = Path(result["file_path"])
        assert pdf_path.exists()
        assert result["file_url"].endswith("/exports/files/job_pdf_test.pdf")

        payload = pdf_path.read_bytes()
        assert payload.startswith(b"%PDF-")
        assert b"STSong-Light" in payload

        reader = PdfReader(str(pdf_path))
        assert len(reader.pages) >= 2
        assert reader.metadata is not None
    finally:
        shutil.rmtree(export_root, ignore_errors=True)


def test_write_export_bundle_generates_markdown_pdf_and_json_artifacts():
    request = _build_request()
    plan = _build_plan(request)
    draft = ExportDraft(title=request.title, subtitle="Kyoto 3 day handbook", sections=[])
    export_root = Path("storage/.pytest_tmp/export-bundle-service") / uuid.uuid4().hex
    export_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(export_root=str(export_root), public_api_url="http://testserver")

    try:
        result = write_export_bundle("job_bundle_test", request, plan, draft, settings, formats=["md", "pdf", "json"])

        assert result["manifest_version"] == 1
        assert result["primary_artifact"] == "pdf"
        assert result["artifact_count"] == 3
        artifacts = {artifact["type"]: artifact for artifact in result["artifacts"]}
        assert set(artifacts) == {"md", "pdf", "json"}

        markdown_path = Path(artifacts["md"]["file_path"])
        assert markdown_path.exists()
        markdown_payload = markdown_path.read_text(encoding="utf-8")
        assert markdown_payload.startswith("# ")
        assert "## " in markdown_payload

        pdf_path = Path(artifacts["pdf"]["file_path"])
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF-")

        json_path = Path(artifacts["json"]["file_path"])
        assert json_path.exists()
        json_payload = json_path.read_text(encoding="utf-8")
        assert '"job_id": "job_bundle_test"' in json_payload
        assert '"formats": [' in json_payload
    finally:
        shutil.rmtree(export_root, ignore_errors=True)

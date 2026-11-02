import type { GeneratedItinerary, ItineraryItem } from "@travelmind/shared-types"
import lake from "@/assets/portal/mist-lake.webp"
import forest from "@/assets/portal/forest-flow.webp"
import cabin from "@/assets/portal/forest-cabin.webp"
import rain from "@/assets/portal/rain-window.webp"

export type JourneyPreviewScenario = "three-days" | "busy-day" | "missing-images"
function stop(id: string, name: string, start: string, end: string, note: string, image?: string, type = "sight"): ItineraryItem {
  return { id, name, type, start_time: start, end_time: end, location: "山湖之间 · 虚构演示地点", score: 0, note, image_urls: image ? [image] : [], image_status: image ? "completed" : "skipped" }
}
export function journeyPreviewData(scenario: JourneyPreviewScenario): GeneratedItinerary {
  const itinerary: GeneratedItinerary = {
    summary: "从湖畔的第一缕晨雾，到山林里亮起的一盏灯。把三天，留给缓缓发生的美好。",
    total_budget_estimate: 1800,
    days: [
      { day_index: 1, title: "湖光与林间", summary: "沿着水岸走走，再去山林里，寻一处安静。", total_cost: 620, items: [
        stop("lake", "在湖畔，慢慢醒来", "09:00", "10:30", "把脚步放慢一点。听水声，看晨雾从远山间轻轻散开。", lake),
        stop("forest", "循着溪流，走进森林", "11:00", "12:00", "沿石径走向林间，把时间交给苔藓、溪水与光。", forest),
        stop("lunch", "一顿不赶时间的午餐", "12:30", "13:30", "找一处安静的小店，尝尝当季的味道。", undefined, "meal"),
        stop("cabin", "把傍晚，交给山居", "15:00", "17:00", "留出一整个下午。窗外是松林，屋里是温暖的灯光。", cabin)
      ] },
      { day_index: 2, title: "雨落的慢时光", summary: "不追逐打卡，把偶然遇见，也写进行程。", total_cost: 580, items: [
        stop("rain", "等一场雨，喝一杯茶", "09:30", "11:00", "看雨滴沿窗流下，远处的灯光在水面上轻轻晃动。", rain),
        stop("walk", "山间小径，随心走走", "11:30", "13:00", "不必走得很远。沿着林间小路，发现不在清单里的风景。", forest),
        stop("dinner", "和今天，好好道别", "17:30", "19:00", "坐下来吃一顿晚餐，记住今天最喜欢的片刻。", undefined, "meal")
      ] },
      { day_index: 3, title: "留一点向往，下次见", summary: "再看一眼湖，再带一点轻盈回到日常。", total_cost: 600, items: [
        stop("last-lake", "最后一段湖边时光", "08:30", "10:00", "让清晨的风，带走一点疲惫。旅程结束，松弛感可以留下。", lake),
        stop("home", "带着好心情，返程", "11:00", "13:00", "实际车次与交通安排，请以正式行程中的已核实信息为准。", undefined, "transport")
      ] }
    ],
    risks: ["当前是设计演示。安排、预算和图片均为示例，不是实时价格或可预订产品。"]
  }
  if (scenario === "busy-day") {
    const originals = [itinerary.days[0].items[0], itinerary.days[0].items[1], itinerary.days[0].items[3]]
    itinerary.days = [{ ...itinerary.days[0], title: "八站，也能从容展开", items: Array.from({ length: 8 }, (_, i) => ({ ...originals[i % 3], id: `busy-${i}`, name: `${originals[i % 3].name} · ${i + 1}`, start_time: `${String(9 + i).padStart(2, "0")}:00`, end_time: `${String(10 + i).padStart(2, "0")}:00` })) }]
    itinerary.summary = "单日八站压力预览：检查长行程的阅读顺序、图片懒加载与连接线对齐。"
  }
  if (scenario === "missing-images") {
    itinerary.days = [{ ...itinerary.days[0], title: "图片没到，旅程也不打断", items: [
      { ...itinerary.days[0].items[0], image_urls: [], image_status: "pending" },
      { ...itinerary.days[0].items[1], image_urls: ["/__journey_missing_image.jpg"], image_backup_urls: [forest] },
      { ...itinerary.days[0].items[3], image_urls: ["/__journey_missing_image.jpg"], image_status: "failed" }
    ] }]
    itinerary.summary = "缺图状态预览：等待补图、主图失败后回退、所有图片失败，都要保持行程可读。"
  }
  return itinerary
}

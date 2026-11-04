import { describe, expect, it } from "vitest"
import { jobPresentation } from "./jobPresentation"
const start = (role: string) => ({ stage: `role.${role}` })
const done = (role: string, state = "completed") => ({ stage: `role.${role}.${state}` })
const view = (events: Array<{stage: string}>, type = "trip.generate") => jobPresentation({type, status: "running", stage: events[events.length - 1]?.stage, timeline_json: events})
describe("并行查询状态", () => {
  it("天气先完成时不再让天气替景点耗时背锅", () => {
    const result = view([start("poi_specialist"), start("weather_specialist"), done("weather_specialist")])
    expect(result.label).toBe("天气已完成，正在查询景点")
    expect(result.branches.map(b => b.statusLabel)).toEqual(["查询中", "已完成"])
  })
  it("景点先完成及住宿交通并行均按实际事件展示", () => {
    expect(view([start("poi_specialist"), start("weather_specialist"), done("poi_specialist")]).label).toBe("景点已完成，正在查询天气")
    expect(view([start("hotel_specialist"), start("transport_specialist"), done("transport_specialist")]).label).toBe("交通已完成，正在查询住宿")
  })
  it("两项完成后不再显示仍在查询", () => {
    expect(view([start("poi_specialist"), done("poi_specialist"), done("weather_specialist")]).label).toBe("参考信息已整理，正在准备下一步")
  })
  it("降级和跳过不伪装为核验成功", () => {
    expect(view([start("poi_specialist"), done("weather_specialist", "degraded")]).label).toBe("天气暂不可用，正在查询景点")
    expect(view([done("hotel_specialist", "skipped"), start("transport_specialist")]).label).toBe("住宿无需查询，正在查询交通")
  })
  it("重试清除旧轮完成标记", () => {
    const result = view([done("weather_specialist"), {stage: "retry_wait"}, start("poi_specialist")])
    expect(result.branches[1].status).toBe("waiting")
  })
  it("不根据耗时或不可信消息猜测完成", () => {
    const result = view([start("poi_specialist"), start("weather_specialist")])
    expect(result.label).toBe("正在查询景点和天气")
    expect(result.branches.every(b => b.status === "running")).toBe(true)
    expect(view([{stage: "role.secret_model.completed"}]).branches).toEqual([])
  })
  it.each(["failed", "cancelled", "completed", "queued"])("%s 不显示仍在查询的分支", status => {
    expect(jobPresentation({status, type: "trip.generate", stage: "role.weather_specialist", timeline_json: [start("weather_specialist")]}).branches).toEqual([])
  })
  it("主行程与补图任务分开，补图期间明确行程已生成", () => {
    const result = jobPresentation({type: "trip.image_enrich", status: "running", stage: "role.weather_specialist"})
    expect(result.label).toBe("行程已生成，正在补充景点图片")
    expect(result.branches).toEqual([])
    expect(result.detail).toContain("已有行程可以继续查看")
  })
})

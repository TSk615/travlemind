import { describe, expect, it } from "vitest"
import { jobPresentation, jobTitle, publicJobError } from "./jobPresentation"

describe("面向用户的中文任务进度", () => {
  it.each([
    ["Brief parser", "正在整理出行需求"], ["POI specialist", "正在挑选合适的景点"],
    ["Weather specialist", "正在查询目的地天气"], ["Hotel specialist", "正在查找合适的住宿"],
    ["Transport specialist", "正在比较出行方式"], ["Itinerary planner", "正在安排每日路线"]
  ])("只把已知角色 %s 映射为中文步骤", (role, label) => {
    const view = jobPresentation({ status: "running", type: "trip.generate", stage: "route_planning", stage_message: `${role}: Uses the planner model to investigate with read-only MCP tools.`, progress_percent: 52 })
    expect(view.label).toBe(label)
    expect(JSON.stringify(view)).not.toMatch(/MCP|specialist|planner model|read-only/)
    expect(view.progress).toBe(52)
  })
  it("未知阶段和恶意输出不回显", () => {
    const view = jobPresentation({ status: "running", stage: "internal_step_v9", stage_message: "<script>alert(1)</script> sk-private /app/storage/logs/job_secret" })
    expect(view.label).toBe("正在处理，请稍候")
    expect(JSON.stringify(view)).not.toMatch(/internal|secret|script|storage/)
    expect(view.progress).toBeNull()
  })
  it.each([NaN, Infinity, -Infinity, undefined])("无有效进度 %s 时不伪造百分比", (progress_percent) => {
    expect(jobPresentation({ status: "running", progress_percent }).progress).toBeNull()
  })
  it("只有完成状态显示百分之百", () => {
    expect(jobPresentation({ status: "running", progress_percent: 100 }).progress).toBe(99)
    expect(jobPresentation({ status: "completed", progress_percent: 20 }).progress).toBe(100)
  })
  it.each(["queued", "retrying", "failed", "cancelled", "completed"])("%s 状态只有安全中文", status => {
    const view = jobPresentation({ status, stage_message: "Transient failure: api_key=PRIVATE /app/storage/logs/foo" })
    expect(JSON.stringify(view)).not.toMatch(/PRIVATE|api_key|storage|Transient/)
    expect(view.label).toMatch(/[一-鿿]/)
  })
  it("正确处理任务名称和图片、导出阶段", () => {
    expect(jobTitle("unknown.job")).toBe("处理进度")
    expect(jobPresentation({ type: "trip.image_enrich", status: "running" }).label).toBe("行程已生成，正在补充景点图片")
    expect(jobPresentation({ type: "export.pdf", status: "running" }).label).toBe("正在整理导出文件")
  })
  it("失败异常和日志路径不泄漏，额度错误仍给出可操作说明", () => {
    expect(publicJobError(new Error("Planner output still invalid: schema_validation_failed (log: /app/storage/logs/jobs/secret.jsonl)"))).toBe("这次处理未能完成，请稍后重试。")
    expect(publicJobError({ code: "generation_quota_exhausted" })).toContain("体验次数已用完")
    expect(publicJobError({ code: "expired_trip_start_date" })).toContain("调整日期")
  })
})


describe("失败原因与退次说明", () => {
  it("日期原因可以穿过重复格式化，且显示已退额度", () => {
    const view = jobPresentation({ status: "failed", type: "trip.generate", public_error_code: "same_day_planning_window_closed", quota_refunded: true })
    expect(view.detail).toContain("明天或之后")
    expect(view.detail).toContain("额度已退回")
    expect(publicJobError(view.detail)).toBe(view.detail)
  })
  it("未退款时绝不承诺已退回，未知服务端原因不回显", () => {
    const view = jobPresentation({ status: "failed", public_error_code: "api_key=secret /app/log", quota_refunded: false })
    expect(view.detail).not.toMatch(/secret|api_key|已退回/)
    expect(publicJobError({ code: "same_day_planning_window_closed" })).toContain("开始日期")
    expect(publicJobError("当天已没有足够 secret")).not.toContain("secret")
  })
})


it("跨天重复景点显示具体中文原因且保留已退次说明", () => {
  const view = jobPresentation({ status: "failed", public_error_code: "planning_duplicate_poi", quota_refunded: true })
  expect(view.detail).toContain("同一景点被重复安排到不同日期")
  expect(view.detail).toContain("不必反复点击继续生成")
  expect(view.detail).toContain("额度已退回")
  expect(publicJobError(view.detail)).toBe(view.detail)
  expect(view.detail).not.toMatch(/POI|jsonl|storage/)
})

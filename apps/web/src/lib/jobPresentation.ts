export interface JobPresentationInput {
  type?: string | null
  status?: string | null
  stage?: string | null
  stage_message?: string | null
  public_error_code?: string | null
  quota_refunded?: boolean
  progress_percent?: number | null
}

const stages: Record<string, string> = {
  brief_parsing: "正在整理出行需求",
  parse_brief: "正在整理出行需求",
  source_search: "正在查询旅行信息",
  source_scoring: "正在核对参考信息",
  evidence_verification: "正在核对参考信息",
  verify_evidence: "正在核对参考信息",
  route_planning: "正在安排每日路线",
  planning: "正在安排每日路线",
  itinerary_planner: "正在安排每日路线",
  hotel_matching: "正在完善住宿安排",
  execution_validation: "正在检查行程细节",
  validate_itinerary: "正在检查行程细节",
  repair_itinerary: "正在完善行程细节",
  export_ready: "正在整理最终结果",
  assemble_result: "正在整理最终结果",
  prompt_compose: "正在整理图片需求",
  source_prepare: "正在准备图片素材",
  image_generate: "正在生成图片",
  asset_persist: "正在保存图片"
}

// Read only known role markers. Never display arbitrary server messages, paths or model names.
const roles: Array<[RegExp, string]> = [
  [/brief[ _-]parser/i, "正在整理出行需求"],
  [/(?:poi[ _-]specialist|research_pois)/i, "正在挑选合适的景点"],
  [/(?:weather[ _-]specialist|research_weather)/i, "正在查询目的地天气"],
  [/(?:hotel[ _-]specialist|research_hotels)/i, "正在查找合适的住宿"],
  [/(?:transport[ _-]specialist|research_transport)/i, "正在比较出行方式"],
  [/(?:itinerary[ _-]planner)/i, "正在安排每日路线"]
]

export function jobTitle(type?: string | null): string {
  return ({ "trip.generate": "生成行程", "trip.refine": "调整行程", "trip.image_enrich": "补充景点图片", "export.pdf": "导出旅行攻略", "image.generate": "生成图片" } as Record<string, string>)[type ?? ""] ?? "处理进度"
}

export function jobPresentation(job: JobPresentationInput) {
  let label: string
  let detail: string
  let progress: number | null = typeof job.progress_percent === "number" && Number.isFinite(job.progress_percent)
    ? Math.max(0, Math.min(99, Math.round(job.progress_percent))) : null
  if (job.status === "completed") {
    label = job.type === "trip.image_enrich" ? "图片已补充" : job.type === "export.pdf" ? "攻略已导出" : job.type === "trip.refine" ? "行程已更新" : "行程已生成"
    detail = job.type === "export.pdf" ? "可以下载并保存旅行攻略了。" : job.type === "trip.image_enrich" ? "可以继续查看行程与图片。" : "可以查看每日安排，并按需要继续调整。"
    progress = 100
  } else if (job.status === "failed") {
    label = "这次未能完成"
    detail = publicJobError({ code: job.public_error_code }, job.type === "export.pdf" ? "攻略暂时无法导出，原行程仍然保留。请稍后再试。" : "这次处理没有完成，已保存的行程不会被覆盖。可以稍后重试，或联系维护者。")
    if (job.quota_refunded) detail += " 本次未扣次数，预占的 1 次体验额度已退回。"
  } else if (job.status === "cancelled") {
    label = "已停止处理"
    detail = "已保存的内容仍然保留。需要时可以重新开始。"
  } else if (job.status === "retrying" || job.stage === "retry_wait") {
    label = "正在重新尝试"
    detail = "刚才的处理暂时没有完成，系统正在尝试恢复，请稍候。"
  } else if (job.status === "queued") {
    label = "正在排队"
    detail = "请求已收到，轮到后会开始处理。"
  } else {
    const role = roles.find(([pattern]) => pattern.test(job.stage ?? "") || pattern.test(job.stage_message ?? ""))
    label = job.type === "trip.image_enrich" ? "正在补充景点图片"
      : job.type === "export.pdf" ? "正在整理导出文件"
      : role?.[1] ?? stages[job.stage ?? ""]
        ?? [...Object.values(stages), ...roles.map(([, value]) => value)].find(value => value === job.stage_message)
        ?? "正在处理，请稍候"
    detail = job.type === "trip.image_enrich" ? "正在查找合适的配图，已有行程可以继续查看。"
      : job.type === "export.pdf" ? "文件准备好后，这里会显示下载入口。"
      : "复杂行程可能需要一些时间，离开页面后仍会继续处理。"
  }
  return { title: jobTitle(job.type), label, detail, progress }
}

// Public copy is an allowlist rather than the raw upstream exception text.
export function publicJobError(error: unknown, fallback = "这次处理未能完成，请稍后重试。"): string {
  const code = error && typeof error === "object" && "code" in error ? String(error.code) : ""
  const messages: Record<string, string> = {
    generation_quota_exhausted: "共享体验次数已用完，仍可查看已有行程。",
    demo_action_forbidden: "公开体验账户暂不支持这项操作。",
    rate_limit_exceeded: "操作有些频繁，请稍后再试。",
    not_authenticated: "登录已失效，请重新登录。",
    invalid_token: "登录已失效，请重新登录。",
    expired_trip_start_date: "出发日期已过期，请调整日期后重新生成。",
    same_day_planning_window_closed: "当天已没有足够的生成和出发准备时间，请把开始日期改为明天或之后，再生成行程。",
    invalid_trip_dates: "结束日期不能早于开始日期，请修改出行日期。",
    planning_duplicate_poi: "同一景点被重复安排到不同日期，行程未通过质量检查。这次没有生成可用行程，请联系维护者排查，不必反复点击继续生成。",
    planning_validation_failed: "生成的行程未通过完整性检查，未保存为正式行程。请重新生成；如果仍然失败，请联系维护者。",
    job_failed: "这次处理未能完成，已有行程仍保留。请稍后重试或联系维护者。",
    job_resume_repair_exhausted: "这次任务无法从旧进度继续，请重新生成行程。这次请求不会扣次。",
    job_resume_checkpoint_missing: "这次暂时无法继续生成，请联系维护者。"
  }
  // Call sites may already hold an allowlisted message. Preserve only exact
  // known copy (optionally with our fixed refund suffix), never arbitrary text.
  if (typeof error === "string") {
    const suffix = " 本次未扣次数，预占的 1 次体验额度已退回。"
    const base = error.endsWith(suffix) ? error.slice(0, -suffix.length) : error
    if (Object.values(messages).includes(base)) return error
  }
  return messages[code] ?? fallback
}

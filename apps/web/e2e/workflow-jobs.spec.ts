import { expect, test, type BrowserContext, type Route } from "@playwright/test"

const user = {
  id: "usr_workflow_e2e",
  email: "workflow@example.com",
  name: "Workflow Traveler",
  is_admin: false,
  is_disabled: false,
  created_at: "2026-09-20T00:00:00Z"
}

const settings = {
  agent: {
    provider_protocol: "openai",
    base_url: "https://llm.example.test/v1",
    model: "workflow-test-model",
    api_key_masked: "sk-***",
    has_api_key: true,
    wire_api: "responses",
    agent_provider: "langgraph",
    configured: true,
    poi_provider_protocol: "openai",
    poi_base_url: "https://llm.example.test/v1",
    poi_model: "workflow-test-model",
    weather_model: "workflow-test-model",
    hotel_model: "workflow-test-model",
    transport_model: "workflow-test-model",
    poi_api_key_masked: "sk-***",
    poi_has_api_key: true,
    poi_wire_api: "responses",
    poi_configured: true
  },
  search: {
    provider: "groksearch",
    transport: "mcp",
    base_url: null,
    api_key_masked: null,
    has_api_key: false,
    timeout_seconds: 30,
    xhs_source_enabled: false,
    configured: false
  },
  image: {
    base_url: null,
    api_key_masked: null,
    has_api_key: false,
    model: null,
    provider: "openai_compatible",
    configured: false
  }
}

const itinerary = {
  summary: "LangGraph 已生成可恢复的京都行程。",
  total_budget_estimate: 3200,
  days: [
    {
      day_index: 1,
      title: "东山慢行",
      summary: "清晨游览寺院，下午保留休息时间。",
      total_cost: 1600,
      items: [
        {
          id: "item_1",
          type: "sight",
          name: "清水寺",
          start_time: "09:00",
          end_time: "11:00",
          location: "京都",
          score: 0.95,
          note: "避开中午客流。"
        }
      ]
    }
  ],
  risks: []
}

function envelope(data: unknown, error: unknown = null) {
  return { data, error, meta: { request_id: "workflow-e2e" } }
}

function trip(withItinerary: boolean, summary = itinerary.summary) {
  return {
    id: "trip_workflow_e2e",
    user_id: user.id,
    title: "广州出发去京都",
    origin: "广州",
    destination: "京都",
    start_date: "2026-10-10",
    end_date: "2026-10-11",
    budget: 6800,
    travelers: 2,
    interests: ["寺庙", "咖啡"],
    accommodation_preference: "安静、交通方便",
    pace: "balanced",
    transport_mode: "rail",
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    itinerary: withItinerary ? { ...itinerary, summary } : null,
    latest_agent_trace: withItinerary
      ? {
          provider: "langgraph",
          workflow_id: "workflow_e2e",
          notes: ["Durable backend workflow completed."],
          agent_runs: [],
          grounding_documents: []
        }
      : null,
    community_post: null
  }
}

function job(jobId: string, type: "trip.generate" | "trip.refine", status: "running" | "completed") {
  return {
    job_id: jobId,
    type,
    trip_id: "trip_workflow_e2e",
    status,
    can_resume: false,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:01Z",
    stage: status === "completed" ? "completed" : "planning",
    stage_message: status === "completed" ? "工作流已完成" : "LangGraph 工作流正在后台运行",
    progress_percent: status === "completed" ? 100 : 45,
    timeline_json: [],
    result: status === "completed" ? { trip_id: "trip_workflow_e2e" } : null,
    error_message: null
  }
}

async function initializeContext(context: BrowserContext) {
  await context.addInitScript(() => window.localStorage.setItem("travelmind_locale", "zh-CN"))
}

async function fulfill(route: Route, data: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(envelope(data))
  })
}

test("generation remains recoverable after the originating page closes", async ({ context }) => {
  await initializeContext(context)
  let workflowCompleted = false
  let jobPolls = 0
  let createPayload: Record<string, unknown> | null = null

  await context.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname

    if (pathname === "/api/v1/me") return fulfill(route, user)
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips" && request.method() === "POST") {
      createPayload = request.postDataJSON() as Record<string, unknown>
      return fulfill(route, trip(false))
    }
    if (pathname === "/api/v1/trips/trip_workflow_e2e/generate" && request.method() === "POST") {
      return fulfill(route, job("job_generate_e2e", "trip.generate", "running"))
    }
    if (pathname === "/api/v1/trips/trip_workflow_e2e") {
      return fulfill(route, trip(workflowCompleted))
    }
    if (pathname === "/api/v1/jobs/job_generate_e2e") {
      jobPolls += 1
      return fulfill(route, job("job_generate_e2e", "trip.generate", workflowCompleted ? "completed" : "running"))
    }
    return fulfill(route, null, 404)
  })

  const originatingPage = await context.newPage()
  await originatingPage.goto("/trips/new")
  await originatingPage.getByRole("button", { name: "创建并生成", exact: true }).click()
  await expect(originatingPage).toHaveURL(/\/trips\/trip_workflow_e2e\?.*jobId=job_generate_e2e/)
  await expect.poll(() => jobPolls).toBeGreaterThan(0)
  expect(createPayload).toMatchObject({ destination: "汕头", pace: "balanced", transport_mode: "rail" })

  const durableUrl = originatingPage.url()
  await originatingPage.close()
  workflowCompleted = true

  const resumedPage = await context.newPage()
  await resumedPage.goto(durableUrl)
  await expect(resumedPage.getByRole("heading", { name: itinerary.summary })).toBeVisible()
  await expect(resumedPage.getByText("job_generate_e2e", { exact: true })).toHaveCount(0)
  await expect(resumedPage.getByRole("status").filter({ hasText: /^行程已生成$/ })).toBeVisible()
  expect(jobPolls).toBeGreaterThan(1)
})

test("refinement submits a durable backend job and reloads the refined trip", async ({ context }) => {
  await initializeContext(context)
  let refinePayload: Record<string, unknown> | null = null
  let refined = false
  const refineSession = {
    id: "refine_session_e2e",
    trip_id: "trip_workflow_e2e",
    messages: [
      {
        id: "message_1",
        role: "user",
        text: "请保留第一天的寺院安排。",
        created_at: "2026-09-20T00:00:00Z"
      }
    ],
    uploaded_guides: [],
    community_sources: [],
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z"
  }

  await context.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname

    if (pathname === "/api/v1/me") return fulfill(route, user)
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips/trip_workflow_e2e") {
      const summary = refined ? "微调完成：第一天寺院安排保持不变。" : itinerary.summary
      return fulfill(route, trip(true, summary))
    }
    if (pathname === "/api/v1/trips/trip_workflow_e2e/refine-session") return fulfill(route, refineSession)
    if (pathname === "/api/v1/community/posts") return fulfill(route, [])
    if (pathname === "/api/v1/trips/trip_workflow_e2e/refine" && request.method() === "POST") {
      refinePayload = request.postDataJSON() as Record<string, unknown>
      refined = true
      return fulfill(route, job("job_refine_e2e", "trip.refine", "completed"))
    }
    if (pathname === "/api/v1/jobs/job_refine_e2e") {
      return fulfill(route, job("job_refine_e2e", "trip.refine", "completed"))
    }
    return fulfill(route, null, 404)
  })

  const page = await context.newPage()
  await page.goto("/trips/trip_workflow_e2e")
  await page.getByRole("button", { name: "快速微调", exact: true }).click()
  await expect(page.getByText("请保留第一天的寺院安排。", { exact: true })).toBeVisible()
  await page.locator("#custom-refine").fill("减少换乘，同时保留第一天安排")
  await page.getByRole("button", { name: "提交微调", exact: true }).click()

  await expect(page.getByRole("heading", { name: "微调完成：第一天寺院安排保持不变。" })).toBeVisible()
  expect(refinePayload).toEqual({ instruction: "减少换乘，同时保留第一天安排", scope: "trip_plan" })
})

test("public progress shows Chinese steps only, even with debug query", async ({ context }) => {
  await initializeContext(context)
  let failed = false
  const privateMessage = "Weather specialist: Uses the planner model to investigate with read-only MCP tools."
  const privateError = "Planner output still invalid after the single shared repair: schema_validation_failed (log: /app/storage/logs/jobs/private.jsonl)"
  await context.route("**/api/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/v1/me") return fulfill(route, user)
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips/trip_workflow_e2e") return fulfill(route, trip(false))
    if (pathname === "/api/v1/jobs/job_private_progress") return fulfill(route, {
      ...job("job_private_progress", "trip.generate", "running"),
      status: failed ? "failed" : "running", stage: "route_planning",
      stage_message: privateMessage, progress_percent: 52,
      error_message: failed ? privateError : null,
      timeline_json: [{ status: "running", stage: "route_planning", stage_message: privateMessage, progress_percent: 52, recorded_at: "2026-11-02T08:53:00Z" }]
    })
    return fulfill(route, null, 404)
  })
  const page = await context.newPage()
  await page.goto("/trips/trip_workflow_e2e?jobId=job_private_progress&debug=1")
  await expect(page.getByRole("status").filter({ hasText: "正在查询目的地天气" })).toBeVisible()
  let text = await page.locator("body").innerText()
  expect(text).not.toMatch(/Weather specialist|MCP tools|job_private_progress|任务诊断|时间线/)
  expect(text).toContain("52%")
  failed = true
  await page.reload()
  await expect(page.getByRole("status").filter({ hasText: "这次未能完成" })).toBeVisible()
  text = await page.locator("body").innerText()
  expect(text).not.toMatch(/schema_validation_failed|Planner output|storage\/logs|\.jsonl|Weather specialist|job_private_progress|任务诊断/)
  expect(text).toContain("已保存的行程不会被覆盖")
})


test("failed generation explains the date and refreshes refunded quota without navigation", async ({ context }) => {
  await initializeContext(context)
  let failed = false
  await context.route("**/api/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/v1/me") return fulfill(route, { ...user, generation_quota: { limit: 5, used: failed ? 0 : 1, remaining: failed ? 5 : 4 } })
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips/trip_workflow_e2e") return fulfill(route, trip(false))
    if (pathname === "/api/v1/jobs/job_refund_e2e") return fulfill(route, {
      ...job("job_refund_e2e", "trip.generate", "running"),
      status: failed ? "failed" : "running",
      public_error_code: failed ? "same_day_planning_window_closed" : null,
      quota_refunded: failed,
      error_message: failed ? "private exception (log: /app/storage/secret.jsonl)" : null
    })
    return fulfill(route, null, 404)
  })
  const page = await context.newPage()
  await page.goto("/trips/trip_workflow_e2e?jobId=job_refund_e2e")
  const banner = page.getByRole("status").filter({ hasText: "公开体验账户" })
  await expect(banner).toContainText("4 / 5")
  failed = true
  await expect(banner).toContainText("5 / 5", { timeout: 15000 })
  await expect(page.getByText(/当天已没有足够的生成和出发准备时间/).first()).toBeVisible()
  await expect(page.getByText(/本次未扣次数/).first()).toBeVisible()
  expect(await page.locator("body").innerText()).not.toMatch(/private exception|secret.jsonl/)
})

test("generation rejected before queue shows safe actionable date reason", async ({ context }) => {
  await initializeContext(context)
  await context.route("**/api/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/v1/me") return fulfill(route, { ...user, generation_quota: { limit: 5, used: 0, remaining: 5 } })
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips/trip_workflow_e2e") return fulfill(route, trip(false))
    if (pathname.endsWith("/generate")) return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify(envelope(null, { code: "same_day_planning_window_closed", message: "private /app/log" })) })
    return fulfill(route, null, 404)
  })
  const page = await context.newPage()
  await page.goto("/trips/trip_workflow_e2e")
  await page.getByRole("button", { name: "生成行程", exact: true }).first().click()
  await expect(page.getByText(/当天已没有足够的生成和出发准备时间/)).toBeVisible()
  expect(await page.locator("body").innerText()).not.toContain("private /app/log")
})


test("terminal duplicate POI failure explains rejection without offering a futile resume", async ({ context }) => {
  await initializeContext(context)
  await context.route("**/api/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/v1/me") return fulfill(route, { ...user, generation_quota: { limit: 5, used: 0, remaining: 5 } })
    if (pathname === "/api/v1/settings/llm") return fulfill(route, settings)
    if (pathname === "/api/v1/trips/trip_workflow_e2e") return fulfill(route, trip(false))
    if (pathname === "/api/v1/jobs/job_duplicate_poi") return fulfill(route, {
      ...job("job_duplicate_poi", "trip.generate", "running"), status: "failed", can_resume: false,
      public_error_code: "planning_duplicate_poi", quota_refunded: true,
      error_message: '行程可执行性校验失败：POI“汕头小公园开埠区”在第 1 天和第 3 天重复 (log: /app/storage/logs/jobs/private.jsonl)'
    })
    return fulfill(route, null, 404)
  })
  const page = await context.newPage()
  await page.goto("/trips/trip_workflow_e2e?jobId=job_duplicate_poi")
  await expect(page.getByText(/同一景点被重复安排到不同日期/).first()).toBeVisible()
  await expect(page.getByRole("button", { name: "继续生成", exact: true })).toHaveCount(0)
  await expect(page.getByRole("status").filter({ hasText: "公开体验账户" })).toContainText("5 / 5")
  expect(await page.locator("body").innerText()).not.toMatch(/private.jsonl|storage\/logs/)
})

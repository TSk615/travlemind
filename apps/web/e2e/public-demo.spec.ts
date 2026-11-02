import { expect, test } from "@playwright/test"

test("public demo shows the shared allowance and uses form intake", async ({ page }) => {
  const user = {
    id: "usr_public_demo", email: "demo@travelmind.example", name: "TravelMind 公开体验",
    locale: "zh-CN", is_admin: false, created_at: "2026-11-02T00:00:00Z",
    generation_quota: { limit: 5, used: 3, remaining: 2 }
  }
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    const data = path === "/api/v1/me" ? user : path === "/api/v1/settings/llm"
      ? { agent: { configured: false }, search: { configured: false }, image: { configured: false } }
      : []
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data, error: null, meta: {} }) })
  })
  await page.goto("/trips/new")
  await expect(page.getByRole("status").filter({ hasText: "公开体验账户" })).toContainText("2 / 5")
  await expect(page.getByRole("status").filter({ hasText: "公开体验账户" })).toContainText("所有访客共享")
  await expect(page.getByRole("button", { name: /直接对话|对话模式|Conversation mode/ })).toHaveCount(0)
  await expect(page.locator('input[type="date"]').first()).toBeVisible()
})

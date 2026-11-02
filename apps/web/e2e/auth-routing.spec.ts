import { expect, test, type Page } from "@playwright/test"

const user = {
  id: "usr_e2e",
  email: "traveler@example.com",
  name: "Traveler",
  is_admin: false,
  is_disabled: false,
  created_at: "2026-07-21T00:00:00Z"
}

function envelope(data: unknown, error: unknown = null) {
  return { data, error, meta: { request_id: "e2e" } }
}

async function mockApi(page: Page) {
  let authenticated = false
  let loginPayload: Record<string, unknown> | null = null

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname

    if (pathname === "/api/v1/auth/login" && request.method() === "POST") {
      loginPayload = request.postDataJSON() as Record<string, unknown>
      authenticated = true
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(envelope(user)) })
      return
    }

    if (pathname === "/api/v1/me") {
      const status = authenticated ? 200 : 401
      const body = authenticated
        ? envelope(user)
        : envelope(null, { code: "unauthorized", message: "Authentication required" })
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
      return
    }

    if (pathname === "/api/v1/auth/refresh") {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify(envelope(null, { code: "unauthorized", message: "No refresh session" }))
      })
      return
    }

    if (pathname === "/api/v1/trips") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(envelope([])) })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify(envelope(null, { code: "not_found", message: `Unhandled E2E route: ${pathname}` }))
    })
  })

  return {
    getLoginPayload: () => loginPayload
  }
}

test("redirects an anonymous visitor from a protected route to login", async ({ page }) => {
  await mockApi(page)

  await page.goto("/trips")

  await expect(page).toHaveURL(/\/login\?redirect=(%2F|\/)trips/)
  await expect(page.locator("#email")).toBeVisible()
  await expect(page.locator("#password")).toBeVisible()
})

test("logs in and returns to the requested trips page", async ({ page }) => {
  const api = await mockApi(page)

  await page.goto("/login?redirect=/trips")
  await page.locator("#email").fill("traveler@example.com")
  await page.locator("#password").fill("correct-horse-battery-staple")
  await page.locator('form button[type="submit"]').click()

  await expect(page).toHaveURL(/\/trips$/)
  await expect(page.getByRole("heading", { name: "我的旅行" })).toBeVisible()
  expect(api.getLoginPayload()).toMatchObject({
    email: "traveler@example.com",
    password: "correct-horse-battery-staple"
  })
})

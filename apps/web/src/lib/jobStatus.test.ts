import { describe, expect, it } from "vitest"
import { isJobActive, isJobTerminal } from "./jobStatus"

describe("job status helpers", () => {
  it.each(["queued", "running", "retrying"])("treats %s as active", (status) => {
    expect(isJobActive(status)).toBe(true)
    expect(isJobTerminal(status)).toBe(false)
  })

  it.each(["completed", "failed", "cancelled"])("treats %s as terminal", (status) => {
    expect(isJobTerminal(status)).toBe(true)
    expect(isJobActive(status)).toBe(false)
  })

  it.each([null, undefined, "", "unknown"])("rejects non-job status %s", (status) => {
    expect(isJobActive(status)).toBe(false)
    expect(isJobTerminal(status)).toBe(false)
  })
})

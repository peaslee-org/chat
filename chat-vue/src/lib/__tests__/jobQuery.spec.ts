import { describe, expect, it, vi } from "vitest"
import { takeJobQuery } from "@/lib/jobQuery"

function fakes(query: Record<string, unknown>) {
  const router = { replace: vi.fn() }
  return { route: { query } as never, router: router as never, replace: router.replace }
}

describe("takeJobQuery", () => {
  it("returns the job id from ?job= and strips it from the URL, keeping other params", () => {
    const { route, router, replace } = fakes({ job: "abc", tab: "photos" })
    expect(takeJobQuery(route, router)).toBe("abc")
    expect(replace).toHaveBeenCalledWith({ query: { tab: "photos" } })
  })

  it("returns null and leaves the URL alone when there is no job param", () => {
    const { route, router, replace } = fakes({ tab: "photos" })
    expect(takeJobQuery(route, router)).toBeNull()
    expect(replace).not.toHaveBeenCalled()
  })

  it("ignores a repeated or empty job param", () => {
    expect(takeJobQuery(fakes({ job: ["a", "b"] }).route, fakes({}).router)).toBeNull()
    expect(takeJobQuery(fakes({ job: "" }).route, fakes({}).router)).toBeNull()
  })
})

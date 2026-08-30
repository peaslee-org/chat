import { describe, expect, it, vi } from "vitest"
import { defineComponent, h } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { takeJobQuery, useJobDeepLink } from "@/lib/jobQuery"

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

describe("useJobDeepLink", () => {
  async function mountWithRouter(open: (id: string) => void) {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/photogrammetry", component: { render: () => null } }] })
    let check!: () => void
    const Host = defineComponent({ setup() { check = useJobDeepLink(open); return () => h("div") } })
    await router.push("/photogrammetry")
    const w = mount(Host, { global: { plugins: [router] } })
    return { router, w, check: () => check() }
  }

  it("opens the job when ?job= changes while the page stays mounted (same-route navigation from a link)", async () => {
    const open = vi.fn()
    const { router, w } = await mountWithRouter(open)
    await router.push({ path: "/photogrammetry", query: { job: "abc" } })
    await flushPromises()   // the watch fires, then router.replace strips the param
    expect(open).toHaveBeenCalledWith("abc")
    expect(router.currentRoute.value.query.job).toBeUndefined()   // stripped, so back/reload won't reopen it
    w.unmount()
  })

  it("the returned check() handles the cold-load case, once the caller's jobs are loaded", async () => {
    const open = vi.fn()
    const { router, check, w } = await mountWithRouter(open)
    await router.replace({ path: "/photogrammetry", query: { job: "cold" } })
    open.mockClear()
    check()
    await flushPromises()
    expect(open).toHaveBeenCalledWith("cold")
    expect(router.currentRoute.value.query.job).toBeUndefined()
    w.unmount()
  })
})

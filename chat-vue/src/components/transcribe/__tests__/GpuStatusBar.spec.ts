import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/gpuApi", () => ({ getGpuState: vi.fn(), warmGpu: vi.fn(), getGpuUsage: vi.fn() }))

import * as api from "@/lib/gpuApi"
import GpuStatusBar from "../GpuStatusBar.vue"
import type { GpuState, GpuUsage } from "@/types"

const T0 = new Date("2026-08-29T10:00:00Z")
const startingState: GpuState = {
  worker_state: "starting", estimated_wait_seconds: 250, warm_until: null, notice: null,
  starting_since: new Date(T0.getTime() - 130_000).toISOString(),
  startup_estimate_seconds: 380, estimate_basis: "measured", estimate_samples: 8, start_kind: "cold",
}
const usage: GpuUsage = {
  today_hours: 0, month_hours: 1, daily_cap_hours: 3, monthly_cap_hours: 30,
  warms_today_for_user: 0, warm_cap_per_user_per_day: 3,
  estimated_month_cost_usd: 0.2, hourly_rate_usd: 0.2,
  actual_month_to_date_usd: null, actual_fetched_at: null,
  startup_median_seconds: 380, startup_samples: 8,
  cold_median_seconds: 380, cold_samples: 7, warm_median_seconds: 65, warm_samples: 2,
  sessions: [
    { started_at: "2026-08-29T09:00:00Z", ended_at: "2026-08-29T09:30:00Z", reason: "job", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: 360, actual_startup_seconds: 445,
      kind: "cold", stages: { capacity: 140, boot: 95, pull: 120, container: 20, init: 70 } },
    { started_at: "2026-08-28T09:00:00Z", ended_at: "2026-08-28T09:30:00Z", reason: "job", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: 400, actual_startup_seconds: 370,
      kind: null, stages: null },
    { started_at: "2026-08-27T09:00:00Z", ended_at: "2026-08-27T09:30:00Z", reason: "warm", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: null, actual_startup_seconds: null,
      kind: null, stages: null },
  ],
}

describe("GpuStatusBar", () => {
  beforeEach(() => {
    setActivePinia(createPinia()); vi.useFakeTimers(); vi.setSystemTime(T0)
    vi.mocked(api.getGpuState).mockResolvedValue(startingState)
    vi.mocked(api.getGpuUsage).mockResolvedValue(usage)
  })
  afterEach(() => { vi.useRealTimers() })

  it("shows remaining and elapsed time while the GPU is starting, with the estimate's basis as a title", async () => {
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    const label = w.find('[data-testid="gpu-label"]')
    expect(label.text()).toBe("GPU starting · ~4 min left · 2:10 elapsed")
    expect(label.attributes("title")).toContain("estimate: median of the last 8 cold starts")
    await vi.advanceTimersByTimeAsync(1_000)
    expect(w.find('[data-testid="gpu-label"]').text()).toContain("2:11 elapsed")
    w.unmount()
  })

  it("says the estimate is a default when nothing has been measured", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue({ ...startingState, estimate_basis: "default", estimate_samples: 0 })
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    expect(w.find('[data-testid="gpu-label"]').attributes("title")).toContain("estimate: default, no cold starts measured yet")
    w.unmount()
  })

  it("names the kind of start in the label title", async () => {
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    expect(w.find('[data-testid="gpu-label"]').attributes("title")).toContain("cold start")
    vi.mocked(api.getGpuState).mockResolvedValue({ ...startingState, start_kind: "warm" })
    w.unmount()
    const w2 = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    expect(w2.find('[data-testid="gpu-label"]').attributes("title")).toContain("warm start")
    w2.unmount()
  })

  it("collapses the startups table by default behind a cold/warm summary, and remembers expanding it", async () => {
    localStorage.removeItem("gpuStartupsOpen")
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w.find('[data-testid="usage-toggle"]').trigger("click")
    const toggle = w.find('[data-testid="startups-toggle"]')
    expect(toggle.text().replace(/\s+/g, " ")).toContain("cold ~6m20s (7) · warm ~1m05s (2)")
    expect(toggle.attributes("aria-expanded")).toBe("false")
    expect(w.find('[data-testid="startups"] table').exists()).toBe(false)
    await toggle.trigger("click")
    expect(toggle.attributes("aria-expanded")).toBe("true")
    expect(w.find('[data-testid="startups"] table').exists()).toBe(true)
    expect(localStorage.getItem("gpuStartupsOpen")).toBe("1")
    w.unmount()
    const w2 = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w2.find('[data-testid="usage-toggle"]').trigger("click")
    expect(w2.find('[data-testid="startups-toggle"]').attributes("aria-expanded")).toBe("true")
    w2.unmount()
    localStorage.removeItem("gpuStartupsOpen")
  })

  it("lists measured startups with kind and stages against their promises", async () => {
    localStorage.setItem("gpuStartupsOpen", "1")
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w.find('[data-testid="usage-toggle"]').trigger("click")
    const panel = w.find('[data-testid="startups"]')
    const head = panel.find("thead").text().replace(/\s+/g, " ")
    for (const col of ["When", "Kind", "Capacity", "Boot", "Pull", "Container", "Init", "Total", "Promised", "Δ"]) expect(head).toContain(col)
    const rows = panel.findAll("tbody tr")
    expect(rows[0].find('[data-testid="kind"]').text()).toBe("cold")
    expect(rows[0].text()).toContain("2m20s")            // capacity
    expect(rows[0].text()).toContain("1m10s")            // init
    expect(rows[1].find('[data-testid="kind"]').text()).toBe("—")
    expect(rows[1].findAll("td").filter(td => td.text() === "—").length).toBeGreaterThanOrEqual(6)  // kind + 5 stages
    localStorage.removeItem("gpuStartupsOpen")
    expect(rows).toHaveLength(2)                       // the warm session has no measurement
    expect(rows[0].text()).toContain("6m00s")          // promised
    expect(rows[0].text()).toContain("7m25s")          // actual
    expect(rows[0].text()).toContain("+1m25s")
    expect(rows[0].find('[data-testid="delta"]').classes()).toContain("text-red-400")
    expect(rows[1].text()).toContain("-0m30s")
    expect(rows[1].find('[data-testid="delta"]').classes()).not.toContain("text-red-400")
    w.unmount()
  })

  it("says so when no startups have been measured", async () => {
    vi.mocked(api.getGpuUsage).mockResolvedValue({ ...usage, startup_median_seconds: null, startup_samples: 0,
      cold_median_seconds: null, cold_samples: 0, warm_median_seconds: null, warm_samples: 0, sessions: [] })
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w.find('[data-testid="usage-toggle"]').trigger("click")
    expect(w.find('[data-testid="startups"]').text()).toContain("no measured starts yet")
    w.unmount()
  })
})

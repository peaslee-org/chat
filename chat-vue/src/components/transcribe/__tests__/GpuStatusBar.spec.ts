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
  startup_estimate_seconds: 380, estimate_basis: "measured", estimate_samples: 8,
}
const usage: GpuUsage = {
  today_hours: 0, month_hours: 1, daily_cap_hours: 3, monthly_cap_hours: 30,
  warms_today_for_user: 0, warm_cap_per_user_per_day: 3,
  estimated_month_cost_usd: 0.2, hourly_rate_usd: 0.2,
  actual_month_to_date_usd: null, actual_fetched_at: null,
  startup_median_seconds: 380, startup_samples: 8,
  sessions: [
    { started_at: "2026-08-29T09:00:00Z", ended_at: "2026-08-29T09:30:00Z", reason: "job", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: 360, actual_startup_seconds: 445 },
    { started_at: "2026-08-28T09:00:00Z", ended_at: "2026-08-28T09:30:00Z", reason: "job", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: 400, actual_startup_seconds: 370 },
    { started_at: "2026-08-27T09:00:00Z", ended_at: "2026-08-27T09:30:00Z", reason: "warm", started_by: "u", end_reason: "idle",
      hours: 0.5, family: "photogrammetry", estimated_startup_seconds: null, actual_startup_seconds: null },
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
    expect(label.attributes("title")).toBe("estimate: median of the last 8 starts")
    await vi.advanceTimersByTimeAsync(1_000)
    expect(w.find('[data-testid="gpu-label"]').text()).toContain("2:11 elapsed")
    w.unmount()
  })

  it("says the estimate is a default when nothing has been measured", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue({ ...startingState, estimate_basis: "default", estimate_samples: 0 })
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    expect(w.find('[data-testid="gpu-label"]').attributes("title")).toBe("estimate: default, no starts measured yet")
    w.unmount()
  })

  it("lists measured startups against their promises in the usage panel", async () => {
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w.find('[data-testid="usage-toggle"]').trigger("click")
    const panel = w.find('[data-testid="startups"]')
    expect(panel.text()).toContain("median 6m20s over 8 starts")
    const rows = panel.findAll("tbody tr")
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
    vi.mocked(api.getGpuUsage).mockResolvedValue({ ...usage, startup_median_seconds: null, startup_samples: 0, sessions: [] })
    const w = mount(GpuStatusBar, { props: { family: "photogrammetry" } })
    await vi.advanceTimersByTimeAsync(0)
    await w.find('[data-testid="usage-toggle"]').trigger("click")
    expect(w.find('[data-testid="startups"]').text()).toContain("no measured starts yet")
    w.unmount()
  })
})

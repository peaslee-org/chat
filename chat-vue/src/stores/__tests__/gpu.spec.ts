import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/gpuApi", () => ({ getGpuState: vi.fn(), warmGpu: vi.fn(), getGpuUsage: vi.fn() }))

import * as api from "@/lib/gpuApi"
import { useGpuStore } from "@/stores/gpu"
import type { GpuState } from "@/types"

const T0 = new Date("2026-08-29T10:00:00Z")
const starting = (sinceSecondsAgo: number): GpuState => ({
  worker_state: "starting",
  start_kind: "cold",
  estimated_wait_seconds: 400 - sinceSecondsAgo,
  warm_until: null,
  notice: null,
  starting_since: new Date(T0.getTime() - sinceSecondsAgo * 1000).toISOString(),
  startup_estimate_seconds: 400,
  estimate_basis: "measured",
  estimate_samples: 8,
})

describe("gpu store — startup countdown", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.useFakeTimers(); vi.setSystemTime(T0) })
  afterEach(() => { vi.useRealTimers() })

  it("derives remaining and elapsed from starting_since and ticks them locally", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue(starting(10))
    const store = useGpuStore()
    await store.refreshState("photogrammetry")
    expect(store.elapsedSeconds).toBe(10)
    expect(store.remainingSeconds).toBe(390)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(store.elapsedSeconds).toBe(15)
    expect(store.remainingSeconds).toBe(385)
  })

  it("clamps remaining at zero once the estimate is exceeded", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue(starting(450))
    const store = useGpuStore()
    await store.refreshState()
    expect(store.remainingSeconds).toBe(0)
    expect(store.elapsedSeconds).toBe(450)
  })

  it("has no countdown when the worker is running or off", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue({
      worker_state: "running", estimated_wait_seconds: 0, warm_until: null, notice: null,
      starting_since: null, startup_estimate_seconds: 400, estimate_basis: "measured", estimate_samples: 8, start_kind: "cold",
    })
    const store = useGpuStore()
    await store.refreshState()
    expect(store.remainingSeconds).toBe(0)
    expect(store.elapsedSeconds).toBeNull()
  })

  it("stops ticking when polling stops", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue(starting(10))
    const store = useGpuStore()
    store.startPolling("photogrammetry")
    await vi.advanceTimersByTimeAsync(0)
    expect(store.elapsedSeconds).toBe(10)
    store.stopPolling()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(store.elapsedSeconds).toBe(10)
  })
})

describe("gpu store — usage", () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it("asks for the usage of the family being polled, so medians and startups match the page", async () => {
    vi.mocked(api.getGpuState).mockResolvedValue(starting(0))
    vi.mocked(api.getGpuUsage).mockResolvedValue({} as never)
    const gpu = useGpuStore()
    gpu.startPolling("photogrammetry")
    await gpu.refreshUsage()
    expect(api.getGpuUsage).toHaveBeenLastCalledWith("photogrammetry")
    gpu.stopPolling()
  })
})

import { describe, expect, it } from "vitest"
import { elapsedLabel, workerStateLabel } from "@/lib/workerState"

describe("workerStateLabel", () => {
  it("shows the remaining minutes while starting", () => {
    expect(workerStateLabel("starting", 250)).toBe("GPU starting · ~4 min left")
  })
  it("never promises less than a minute", () => {
    expect(workerStateLabel("starting", 10)).toBe("GPU starting · ~1 min left")
  })
  it("keeps the ready and off labels", () => {
    expect(workerStateLabel("running")).toBe("GPU ready")
    expect(workerStateLabel("off")).toBe("GPU off — starts on your next job")
  })
})

describe("elapsedLabel", () => {
  it("formats the time since the worker was launched as m:ss", () => {
    expect(elapsedLabel("2026-08-29T10:00:00Z", new Date("2026-08-29T10:02:10Z"))).toBe("2:10")
    expect(elapsedLabel("2026-08-29T10:00:00Z", new Date("2026-08-29T10:00:05Z"))).toBe("0:05")
  })
})

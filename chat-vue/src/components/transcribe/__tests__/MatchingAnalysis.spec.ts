import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  fetchTurnDistances: vi.fn(),
  compileTranscript: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import MatchingAnalysis from "../MatchingAnalysis.vue"
import { useTranscribeStore } from "@/stores/transcribe"
import { seedThresholds, useMatchingThresholds } from "@/composables/useMatchingThresholds"

const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 }
const turns = [{ start_time: 0, end_time: 1, text: "a", candidates: [{ candidate_id: "c1", speaker_name: "Jane", cosine_dist: 0.1 }] }]

async function mountOpen() {
  setActivePinia(createPinia())
  const store = useTranscribeStore()
  store.activeJobId = "t1"
  store.activeTranscript = { segments: [], turns: [], settings, compiled_at: "2026-09-03T12:00:00Z" }
  store.turnDistanceData["t1"] = turns
  seedThresholds(settings)
  const w = mount(MatchingAnalysis, { props: { jobId: "t1" } })
  await w.find("button").trigger("click")   // open the panel
  await flushPromises()
  return { store, w }
}

describe("MatchingAnalysis — re-compile", () => {
  beforeEach(() => {
    vi.mocked(api.fetchTurnDistances).mockReset().mockResolvedValue({ turns })
    vi.mocked(api.compileTranscript).mockReset()
  })

  it("hides Re-compile while the sliders equal the embedded settings", async () => {
    const { w } = await mountOpen()
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })

  it("shows Re-compile and Reset once a slider moves, and Reset restores", async () => {
    const { w } = await mountOpen()
    useMatchingThresholds().cosineDistThreshold.value = 0.4
    await flushPromises()
    expect(w.find('[data-testid="recompile"]').exists()).toBe(true)
    await w.find('[data-testid="reset-thresholds"]').trigger("click")
    expect(useMatchingThresholds().cosineDistThreshold.value).toBe(0.25)
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })

  it("Re-compile posts the current sliders and hides itself on success", async () => {
    const { w } = await mountOpen()
    useMatchingThresholds().cosineDistThreshold.value = 0.4
    await flushPromises()
    const next = { segments: [], turns: [], settings: { ...settings, cosine_dist_threshold: 0.4 }, compiled_at: "2026-09-03T12:01:00Z" }
    vi.mocked(api.compileTranscript).mockResolvedValue(next as never)
    await w.find('[data-testid="recompile"]').trigger("click")
    await flushPromises()
    expect(api.compileTranscript).toHaveBeenCalledWith("t1", { ...settings, cosine_dist_threshold: 0.4 })
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })
})

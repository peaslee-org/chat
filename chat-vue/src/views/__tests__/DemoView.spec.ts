import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount, RouterLinkStub } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@google/model-viewer", () => ({ ModelViewerElement: class {} }))
vi.mock("@/lib/publicApi", () => ({
  getShowcase: vi.fn(),
  getPublicScan: vi.fn(),
  getPublicTranscription: vi.fn(),
  getPublicConversation: vi.fn(),
}))

import { getPublicScan, getPublicTranscription, getShowcase } from "@/lib/publicApi"
import DemoView from "../DemoView.vue"

const showcase = {
  scans: [{ job_id: "j1", name: "cat", image_count: 22, status: "complete", preview_url: null, created_at: "2026-09-01T00:00:00Z" }],
  transcriptions: [],
  conversations: [],
}

function mountDemo() {
  localStorage.clear()
  setActivePinia(createPinia())
  return mount(DemoView, { global: { stubs: { RouterLink: RouterLinkStub } } })
}

describe("DemoView", () => {
  it("renders the showcase and auto-opens the first complete scan", async () => {
    vi.mocked(getShowcase).mockResolvedValue(showcase as never)
    vi.mocked(getPublicScan).mockResolvedValue({ ...showcase.scans[0], warnings: [], matched: 20, total: 22, mesh_url: "https://signed", expires_at: null, completed_at: null } as never)
    const w = mountDemo()
    await flushPromises()
    expect(w.find('[data-testid="section-scans"]').exists()).toBe(true)
    expect(getPublicScan).toHaveBeenCalledWith("j1")
    expect(w.find('[data-testid="sign-in"]').exists()).toBe(true)
  })

  it("shows the error note when the API is unreachable", async () => {
    vi.mocked(getShowcase).mockRejectedValue(new Error("down"))
    const w = mountDemo()
    await flushPromises()
    expect(w.find('[data-testid="demo-error"]').exists()).toBe(true)
  })

  it("shows a section error when opening a scan fails", async () => {
    vi.mocked(getShowcase).mockResolvedValue(showcase as never)
    vi.mocked(getPublicScan).mockRejectedValue(new Error("gone"))
    const w = mountDemo()
    await flushPromises()
    expect(w.find('[data-testid="section-error"]').exists()).toBe(true)
  })

  it("renders a public transcript's compiled turns with speaker labels", async () => {
    vi.mocked(getShowcase).mockResolvedValue({
      ...showcase,
      scans: [],
      transcriptions: [{ job_id: "t1", created_at: "2026-09-01T00:00:00Z", duration_seconds: 16, segment_count: 5, speaker_count: 2 }],
    } as never)
    vi.mocked(getPublicTranscription).mockResolvedValue({
      job_id: "t1", created_at: "2026-09-01T00:00:00Z", duration_seconds: 16, segment_count: 5, speaker_count: 2,
      segments: [{ segment_id: "s", anonymous_label: "PROBABLY_Barry", speaker_name: null, start_time: 8.7, end_time: 11.4, text: "Sounds good" }],
      turns: [{ start_time: 8.55, end_time: 11.27, text: "Sounds good", label: "Barry", match_type: "medium" }],
      settings: { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 },
      compiled_at: "2026-09-03T12:00:00Z",
    } as never)
    const w = mountDemo()
    await flushPromises()
    await w.find('[data-testid="transcription-chip"]').trigger("click")
    await flushPromises()
    expect(w.text()).toContain("Barry")
    expect(w.text()).not.toContain("PROBABLY_Barry")
  })
})

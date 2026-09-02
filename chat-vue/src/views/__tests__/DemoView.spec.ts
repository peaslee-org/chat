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

import { getPublicScan, getShowcase } from "@/lib/publicApi"
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
})

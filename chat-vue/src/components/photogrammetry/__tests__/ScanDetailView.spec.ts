import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@google/model-viewer", () => ({ ModelViewerElement: class {} }))
vi.mock("@/lib/photogrammetryApi", () => ({
  fetchJobPhotos: vi.fn(),
  fetchSamplePhotos: vi.fn(),
  deleteJob: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  createJob: vi.fn(),
  confirmJob: vi.fn(),
  createSampleJob: vi.fn(),
  getMeshUrl: vi.fn(),
  uploadToS3: vi.fn(),
}))

import * as api from "@/lib/photogrammetryApi"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanDetailView from "../ScanDetailView.vue"
import type { PhotogrammetryJob } from "@/types"

const photo = { filename: "0001.jpg", url: "https://s3/full/0001.jpg", thumb_url: "https://s3/thumbs/0001.jpg", status: null }

function job(overrides: Partial<PhotogrammetryJob> = {}): PhotogrammetryJob {
  return {
    job_id: "j1", name: "Scan", status: "processing", stage: "sfm", image_count: 1, preview_url: null,
    error_message: null, warnings: [], mock: false, created_at: "2026-08-29T10:00:00Z", updated_at: "2026-08-29T10:00:00Z",
    completed_at: null, ...overrides,
  } as PhotogrammetryJob
}

const esc = () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }))

describe("ScanDetailView — closing a scan", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.fetchJobPhotos).mockReset().mockResolvedValue({ photos: [photo], matched: null, total: 1 })
  })

  function mountSelected() {
    const store = usePhotogrammetryStore()
    store.jobs.push(job())
    store.selectJob("j1")
    const w = mount(ScanDetailView, { props: { formMode: "closed" }, attachTo: document.body })
    return { store, w }
  }

  it("the ✕ button clears the selection", async () => {
    const { store, w } = mountSelected()
    await w.vm.$nextTick()
    await w.find('[aria-label="Close scan"]').trigger("click")
    expect(store.activeJobId).toBeNull()
    expect(w.text()).toContain("Select a scan or start a new one")
    w.unmount()
  })

  it("Escape clears the selection when no photo overlay is open", async () => {
    const { store, w } = mountSelected()
    await w.vm.$nextTick()
    esc(); await w.vm.$nextTick()
    expect(store.activeJobId).toBeNull()
    w.unmount()
  })

  it("Escape with the photo overlay open closes only the overlay", async () => {
    const { store, w } = mountSelected()
    await vi.waitFor(() => expect(w.findAll("img").length).toBeGreaterThan(0))
    await w.findAll("img")[0].trigger("click")
    expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(true)
    esc(); await w.vm.$nextTick()
    expect(w.find('[data-testid="photo-overlay"]').exists()).toBe(false)
    expect(store.activeJobId).toBe("j1")
    w.unmount()
  })

  it("refetches while thumbnails are still generating, and stops when they arrive", async () => {
    vi.useFakeTimers()
    try {
      const pending = { photos: [{ ...photo, thumb_url: null }], matched: null, total: 1 }
      const ready = { photos: [photo], matched: null, total: 1 }
      vi.mocked(api.fetchJobPhotos).mockReset()
        .mockResolvedValueOnce(pending)
        .mockResolvedValueOnce(pending)
        .mockResolvedValue(ready)
      const { w } = mountSelected()
      await flushPromises()
      expect(api.fetchJobPhotos).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(5000)
      expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)   // still pending → poll again
      await vi.advanceTimersByTimeAsync(5000)
      expect(api.fetchJobPhotos).toHaveBeenCalledTimes(3)   // thumbnails arrived
      await vi.advanceTimersByTimeAsync(20000)
      expect(api.fetchJobPhotos).toHaveBeenCalledTimes(3)   // polling stopped
      w.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it("refetches the photos when the job reaches a terminal status", async () => {
    const { store, w } = mountSelected()
    await vi.waitFor(() => expect(api.fetchJobPhotos).toHaveBeenCalledTimes(1))
    vi.mocked(api.fetchJobPhotos).mockResolvedValueOnce({ photos: [{ ...photo, status: "unregistered" }], matched: 0, total: 1 })
    store.jobs[0] = job({ status: "failed", error_message: "Only 0 of 1 photos could be matched" })
    await vi.waitFor(() => expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2))
    await vi.waitFor(() => expect(w.find('[data-testid="status-tag"]').text()).toBe("not matched"))
    w.unmount()
  })
})

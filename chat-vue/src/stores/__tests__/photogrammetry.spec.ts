import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/photogrammetryApi", () => ({
  fetchJobPhotos: vi.fn(),
  fetchSamplePhotos: vi.fn(),
  deleteJob: vi.fn().mockResolvedValue(undefined),
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

const photo = { filename: "0001.jpg", url: "u", thumb_url: "t", status: null }
const body = { photos: [photo], matched: null, total: 1 }

describe("photogrammetry store — photos", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.fetchJobPhotos).mockReset().mockResolvedValue(body)
    vi.mocked(api.fetchSamplePhotos).mockReset().mockResolvedValue({ name: "Sample scan", image_count: 1, photos: [photo] })
  })

  it("fetchJobPhotos caches the full response per job id", async () => {
    const store = usePhotogrammetryStore()
    expect(await store.fetchJobPhotos("j1")).toEqual(body)
    expect(await store.fetchJobPhotos("j1")).toEqual(body)
    await store.fetchJobPhotos("j2")
    expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)
  })

  it("does not cache a photo list smaller than the job's image count", async () => {
    // The Photos pane can ask half a second after job creation, before the presigned PUTs have
    // landed — caching that near-empty answer froze the pane for the session (2026-08-31).
    const store = usePhotogrammetryStore()
    store.jobs.push({ job_id: "j1", image_count: 2 } as never)
    vi.mocked(api.fetchJobPhotos).mockResolvedValueOnce({ photos: [], matched: null, total: 0 })
    expect((await store.fetchJobPhotos("j1")).photos).toEqual([])
    expect((await store.fetchJobPhotos("j1")).photos).toEqual([photo])
    expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)
  })

  it("fetchJobPhotos with force refetches and replaces the cache", async () => {
    const store = usePhotogrammetryStore()
    await store.fetchJobPhotos("j1")
    const after = { photos: [{ ...photo, status: "unregistered" }], matched: 0, total: 1 }
    vi.mocked(api.fetchJobPhotos).mockResolvedValueOnce(after)
    expect(await store.fetchJobPhotos("j1", { force: true })).toEqual(after)
    expect(await store.fetchJobPhotos("j1")).toEqual(after)
    expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)
  })

  it("clearSelection drops the active job", () => {
    const store = usePhotogrammetryStore()
    store.selectJob("j1")
    expect(store.activeJobId).toBe("j1")
    store.clearSelection()
    expect(store.activeJobId).toBeNull()
  })

  it("deleting a job drops its cached photos", async () => {
    const store = usePhotogrammetryStore()
    await store.fetchJobPhotos("j1")
    await store.deleteJob("j1")
    await store.fetchJobPhotos("j1")
    expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)
  })

  it("fetchSamplePhotos passes the sample set through", async () => {
    const store = usePhotogrammetryStore()
    expect(await store.fetchSamplePhotos()).toEqual({ name: "Sample scan", image_count: 1, photos: [photo] })
  })
})

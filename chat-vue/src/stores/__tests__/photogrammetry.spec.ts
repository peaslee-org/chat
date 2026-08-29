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

const photo = { filename: "0001.jpg", url: "u", thumb_url: "t" }

describe("photogrammetry store — photos", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.fetchJobPhotos).mockReset().mockResolvedValue([photo])
    vi.mocked(api.fetchSamplePhotos).mockReset().mockResolvedValue({ name: "Sample scan", image_count: 1, photos: [photo] })
  })

  it("fetchJobPhotos caches per job id", async () => {
    const store = usePhotogrammetryStore()
    expect(await store.fetchJobPhotos("j1")).toEqual([photo])
    expect(await store.fetchJobPhotos("j1")).toEqual([photo])
    await store.fetchJobPhotos("j2")
    expect(api.fetchJobPhotos).toHaveBeenCalledTimes(2)
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

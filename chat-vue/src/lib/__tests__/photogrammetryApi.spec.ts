import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/axios", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}))
vi.mock("@/lib/transcribeApi", () => ({ uploadToS3: vi.fn() }))

import { apiClient } from "@/lib/axios"
import { fetchJobPhotos, fetchSamplePhotos } from "@/lib/photogrammetryApi"

const get = vi.mocked(apiClient.get)

const photo = { filename: "0001.jpg", url: "https://s3/full/0001.jpg", thumb_url: "https://s3/thumbs/0001.jpg" }

describe("photogrammetry api client — photos", () => {
  beforeEach(() => get.mockReset())

  it("fetchSamplePhotos GETs /samples and returns the body", async () => {
    get.mockResolvedValueOnce({ data: { name: "Sample scan", image_count: 1, photos: [photo] } })
    const res = await fetchSamplePhotos()
    expect(get).toHaveBeenCalledWith("/api/v1/photogrammetry/samples")
    expect(res).toEqual({ name: "Sample scan", image_count: 1, photos: [photo] })
  })

  it("fetchJobPhotos GETs /jobs/{id}/photos and returns the photo list", async () => {
    get.mockResolvedValueOnce({ data: { photos: [photo] } })
    const res = await fetchJobPhotos("job-1")
    expect(get).toHaveBeenCalledWith("/api/v1/photogrammetry/jobs/job-1/photos")
    expect(res).toEqual([photo])
  })
})

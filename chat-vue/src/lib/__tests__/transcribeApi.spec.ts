import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/axios", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn() },
}))

import { apiClient } from "@/lib/axios"
import { getSamples, setJobVisibility } from "@/lib/transcribeApi"

const get = vi.mocked(apiClient.get)
const patch = vi.mocked(apiClient.patch)

describe("transcribe api client — jobs", () => {
  beforeEach(() => patch.mockReset())

  it("setJobVisibility PATCHes /jobs/{id} with is_public and returns TranscriptionJob", async () => {
    patch.mockResolvedValueOnce({ data: { job_id: "t1", status: "complete", is_public: true } })
    const res = await setJobVisibility("t1", true)
    expect(patch).toHaveBeenCalledWith("/api/v1/transcribe/jobs/t1", { is_public: true })
    expect(res.is_public).toBe(true)
  })
})

describe("transcribe api client — samples", () => {
  beforeEach(() => get.mockReset())

  it("getSamples GETs /samples and returns the bundle", async () => {
    const body = {
      name: "Sample conversation",
      audio: { filename: "conversation", url: "https://dl/samples/conversation.wav" },
      speakers: [
        { speaker_name: "Barry", url: "https://dl/samples/speakers/barry.wav" },
        { speaker_name: "Jane", url: "https://dl/samples/speakers/jane.wav" },
      ],
    }
    get.mockResolvedValueOnce({ data: body })
    const res = await getSamples()
    expect(get).toHaveBeenCalledWith("/api/v1/transcribe/samples")
    expect(res).toEqual(body)
  })
})

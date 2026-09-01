import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/axios", () => ({
  apiClient: { patch: vi.fn() },
}))

import { apiClient } from "@/lib/axios"
import { setJobVisibility } from "@/lib/transcribeApi"

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

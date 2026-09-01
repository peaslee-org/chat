import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/axios", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn() },
}))

import { apiClient } from "@/lib/axios"
import { getPublicScan, getShowcase, getPublicTranscription, getPublicConversation } from "../publicApi"

const get = apiClient.get as ReturnType<typeof vi.fn>

describe("publicApi", () => {
  beforeEach(() => vi.clearAllMocks())

  it("fetches the showcase", async () => {
    get.mockResolvedValue({ data: { scans: [], transcriptions: [], conversations: [] } })
    const out = await getShowcase()
    expect(get).toHaveBeenCalledWith("/api/v1/public/showcase")
    expect(out.scans).toEqual([])
  })

  it("fetches a public scan", async () => {
    get.mockResolvedValue({ data: { job_id: "j1" } })
    await getPublicScan("j1")
    expect(get).toHaveBeenCalledWith("/api/v1/public/photogrammetry/j1")
  })

  it("fetches a public transcription", async () => {
    get.mockResolvedValue({ data: { job_id: "t1", segments: [] } })
    await getPublicTranscription("t1")
    expect(get).toHaveBeenCalledWith("/api/v1/public/transcriptions/t1")
  })

  it("fetches a public conversation", async () => {
    get.mockResolvedValue({ data: { conversation_id: "c1", messages: [] } })
    await getPublicConversation("c1")
    expect(get).toHaveBeenCalledWith("/api/v1/public/conversations/c1")
  })
})

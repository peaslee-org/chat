import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({ setJobVisibility: vi.fn() }))

import * as api from "@/lib/transcribeApi"
import { useTranscribeStore } from "@/stores/transcribe"
import type { TranscriptionJob } from "@/types"

function job(overrides: Partial<TranscriptionJob> = {}): TranscriptionJob {
  return {
    job_id: "t1",
    status: "complete",
    speaker_count_hint: 2,
    language: "en-US",
    speaker_ids: [],
    error_message: null,
    partial_transcript_available: false,
    matched_speaker_count: null,
    total_segment_count: null,
    created_at: "2026-08-29T10:00:00Z",
    updated_at: "2026-08-29T10:00:00Z",
    completed_at: null,
    is_public: false,
    ...overrides,
  } as TranscriptionJob
}

describe("transcribe store — visibility", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.setJobVisibility).mockReset()
  })

  it("setVisibility PATCHes through the api and updates the job in place", async () => {
    const store = useTranscribeStore()
    store.jobs.push(job())
    vi.mocked(api.setJobVisibility).mockResolvedValue(job({ is_public: true }))

    await store.setVisibility("t1", true)

    expect(api.setJobVisibility).toHaveBeenCalledWith("t1", true)
    expect(store.jobs.find((j) => j.job_id === "t1")?.is_public).toBe(true)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  setJobVisibility: vi.fn(),
  createSampleJob: vi.fn(),
  createJob: vi.fn(),
  uploadToS3: vi.fn(),
  confirmJobUpload: vi.fn(),
  listSpeakers: vi.fn(),
}))

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

describe("transcribe store — speaker refresh after job creation", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.mocked(api.listSpeakers).mockReset().mockResolvedValue({ items: [], next_cursor: null })
    vi.mocked(api.createSampleJob).mockReset()
    vi.mocked(api.createJob).mockReset()
    vi.mocked(api.uploadToS3).mockReset().mockResolvedValue(undefined)
    vi.mocked(api.confirmJobUpload).mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => { vi.useRealTimers() })

  it("submitSampleJob refetches the speaker list once the sample job is created", async () => {
    vi.mocked(api.createSampleJob).mockResolvedValue({ job_id: "sj1", speaker_ids: ["s1", "s2"] })
    const store = useTranscribeStore()

    await store.submitSampleJob()

    expect(api.listSpeakers).toHaveBeenCalledTimes(1)
  })

  it("submitJob refetches the speaker list when speaker_ids are passed", async () => {
    vi.mocked(api.createJob).mockResolvedValue({ job_id: "j1", upload_url: "https://s3.example/upload" })
    const store = useTranscribeStore()
    const file = new File(["audio"], "a.wav", { type: "audio/wav" })

    await store.submitJob(file, { speakerCountHint: 2, speakerIds: ["s1"], language: "en-US" })

    expect(api.listSpeakers).toHaveBeenCalledTimes(1)
  })

  it("submitJob does not refetch the speaker list when no speaker_ids are passed", async () => {
    vi.mocked(api.createJob).mockResolvedValue({ job_id: "j2", upload_url: "https://s3.example/upload" })
    const store = useTranscribeStore()
    const file = new File(["audio"], "a.wav", { type: "audio/wav" })

    await store.submitJob(file, { speakerCountHint: 2, speakerIds: [], language: "en-US" })

    expect(api.listSpeakers).not.toHaveBeenCalled()
  })

  it("a failed speaker refresh does not stop submitSampleJob from tracking the job", async () => {
    vi.mocked(api.createSampleJob).mockResolvedValue({ job_id: "sj2", speaker_ids: ["s1"] })
    vi.mocked(api.listSpeakers).mockRejectedValue(new Error("network error"))
    const store = useTranscribeStore()

    const jobId = await store.submitSampleJob()

    expect(jobId).toBe("sj2")
    expect(store.jobs.some((j) => j.job_id === "sj2")).toBe(true)
  })

  it("a failed speaker refresh does not stop submitJob from tracking the job", async () => {
    vi.mocked(api.createJob).mockResolvedValue({ job_id: "j3", upload_url: "https://s3.example/upload" })
    vi.mocked(api.listSpeakers).mockRejectedValue(new Error("network error"))
    const store = useTranscribeStore()
    const file = new File(["audio"], "a.wav", { type: "audio/wav" })

    const jobId = await store.submitJob(file, { speakerCountHint: 2, speakerIds: ["s1"], language: "en-US" })

    expect(jobId).toBe("j3")
    expect(store.jobs.some((j) => j.job_id === "j3")).toBe(true)
  })
})

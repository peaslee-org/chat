import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  setJobVisibility: vi.fn(),
  createSampleJob: vi.fn(),
  createJob: vi.fn(),
  uploadToS3: vi.fn(),
  confirmJobUpload: vi.fn(),
  listSpeakers: vi.fn(),
  rerunJob: vi.fn(),
  getSamples: vi.fn(),
  getJobAudioUrl: vi.fn(),
  getSampleAudioUrl: vi.fn(),
  getTranscript: vi.fn(),
  compileTranscript: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import { useTranscribeStore } from "@/stores/transcribe"
import { useMatchingThresholds } from "@/composables/useMatchingThresholds"
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

  it("submitJob adds the pending job to state before the speaker refresh resolves", async () => {
    vi.mocked(api.createJob).mockResolvedValue({ job_id: "j4", upload_url: "https://s3.example/upload" })
    let resolveSpeakers!: (v: { items: never[]; next_cursor: null }) => void
    vi.mocked(api.listSpeakers).mockReturnValue(
      new Promise((resolve) => { resolveSpeakers = resolve })
    )
    const store = useTranscribeStore()
    const file = new File(["audio"], "a.wav", { type: "audio/wav" })

    const submitPromise = store.submitJob(file, { speakerCountHint: 2, speakerIds: ["s1"], language: "en-US" })
    // Flush microtasks so createJob resolves and the pending job is unshifted,
    // without letting the still-pending speaker refresh resolve.
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    expect(store.jobs.some((j) => j.job_id === "j4" && j.status === "pending")).toBe(true)
    expect(api.uploadToS3).not.toHaveBeenCalled()

    resolveSpeakers({ items: [], next_cursor: null })
    await submitPromise
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

describe("transcribe store — rerunJob", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.rerunJob).mockReset()
  })

  it("adds the new job, selects it, and returns its id", async () => {
    const newJob = job({ job_id: "j-rerun", status: "transcribing" })
    vi.mocked(api.rerunJob).mockResolvedValue(newJob)
    const store = useTranscribeStore()
    store.jobs.push(job({ job_id: "j-source", status: "failed" }))

    const result = await store.rerunJob("j-source")

    expect(api.rerunJob).toHaveBeenCalledWith("j-source")
    expect(result).toBe("j-rerun")
    expect(store.jobs.some((j) => j.job_id === "j-rerun")).toBe(true)
    expect(store.activeJobId).toBe("j-rerun")
  })

  it("propagates errors without adding a job", async () => {
    vi.mocked(api.rerunJob).mockRejectedValue(new Error("gone"))
    const store = useTranscribeStore()
    store.jobs.push(job({ job_id: "j-source", status: "failed" }))

    await expect(store.rerunJob("j-source")).rejects.toThrow("gone")
    expect(store.jobs.some((j) => j.job_id !== "j-source")).toBe(false)
  })
})

describe("transcribe store — sample preview", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getSamples).mockReset()
  })

  it("loadSamplePreview passes the sample bundle through", async () => {
    const preview = {
      name: "Sample conversation",
      audio: { filename: "conversation", url: "https://dl/samples/conversation.wav" },
      speakers: [
        { speaker_name: "Barry", url: "https://dl/samples/speakers/barry.wav" },
        { speaker_name: "Jane", url: "https://dl/samples/speakers/jane.wav" },
      ],
    }
    vi.mocked(api.getSamples).mockResolvedValue(preview)
    const store = useTranscribeStore()

    expect(await store.loadSamplePreview()).toEqual(preview)
    expect(api.getSamples).toHaveBeenCalledOnce()
  })

  it("propagates fetch failures", async () => {
    vi.mocked(api.getSamples).mockRejectedValue(new Error("not uploaded"))
    const store = useTranscribeStore()

    await expect(store.loadSamplePreview()).rejects.toThrow("not uploaded")
  })
})

describe("transcribe store — job audio url", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getJobAudioUrl).mockReset()
  })

  it("fetchJobAudioUrl fetches and caches, keyed by job id", async () => {
    vi.mocked(api.getJobAudioUrl).mockResolvedValue({
      url: "https://dl/a", download_url: "https://dl/a?dl=x",
      filename: "job-audio", expires_at: "2099-01-01T00:00:00Z",
    })
    const store = useTranscribeStore()

    const res = await store.fetchJobAudioUrl("j1")

    expect(api.getJobAudioUrl).toHaveBeenCalledWith("j1")
    expect(res).toEqual({
      url: "https://dl/a", downloadUrl: "https://dl/a?dl=x",
      filename: "job-audio", expiresAt: new Date("2099-01-01T00:00:00Z").getTime(),
    })
    expect(store.jobAudioUrls["j1"]).toEqual(res)
  })

  it("fetchJobAudioUrl does not refetch while the cached entry is far from expiry", async () => {
    vi.mocked(api.getJobAudioUrl).mockResolvedValue({
      url: "https://dl/a", download_url: "https://dl/a?dl=x",
      filename: "job-audio", expires_at: "2099-01-01T00:00:00Z",
    })
    const store = useTranscribeStore()

    await store.fetchJobAudioUrl("j1")
    await store.fetchJobAudioUrl("j1")

    expect(api.getJobAudioUrl).toHaveBeenCalledTimes(1)
  })

  it("propagates a 404 (expired audio) to the caller", async () => {
    const err = Object.assign(new Error("not found"), { response: { status: 404 } })
    vi.mocked(api.getJobAudioUrl).mockRejectedValue(err)
    const store = useTranscribeStore()

    await expect(store.fetchJobAudioUrl("j1")).rejects.toThrow("not found")
    expect(store.jobAudioUrls["j1"]).toBeUndefined()
  })
})

describe("transcribe store — sample audio url", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getSampleAudioUrl).mockReset()
  })

  it("fetchSampleAudioUrl fetches and caches, keyed by sample id", async () => {
    vi.mocked(api.getSampleAudioUrl).mockResolvedValue({
      url: "https://dl/s", download_url: "https://dl/s?dl=x",
      filename: "speaker-sample", expires_at: "2099-01-01T00:00:00Z",
    })
    const store = useTranscribeStore()

    const res = await store.fetchSampleAudioUrl("sp1", "sm1")

    expect(api.getSampleAudioUrl).toHaveBeenCalledWith("sp1", "sm1")
    expect(res.url).toBe("https://dl/s")
    expect(store.sampleAudioUrls["sm1"]).toEqual(res)
  })

  it("fetchSampleAudioUrl does not refetch while the cached entry is far from expiry", async () => {
    vi.mocked(api.getSampleAudioUrl).mockResolvedValue({
      url: "https://dl/s", download_url: "https://dl/s?dl=x",
      filename: "speaker-sample", expires_at: "2099-01-01T00:00:00Z",
    })
    const store = useTranscribeStore()

    await store.fetchSampleAudioUrl("sp1", "sm1")
    await store.fetchSampleAudioUrl("sp1", "sm1")

    expect(api.getSampleAudioUrl).toHaveBeenCalledTimes(1)
  })
})

describe("compiled transcripts", () => {
  const transcript = (over: Record<string, unknown> = {}) => ({
    segments: [],
    turns: [{ start_time: 0, end_time: 1, text: "a", label: "Jane", match_type: "high" }],
    settings: { cosine_dist_threshold: 0.3, separation_min: 0.1, quality_min: 0, confidence_min: 0 },
    compiled_at: "2026-09-03T12:00:00Z",
    ...over,
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getTranscript).mockReset()
    vi.mocked(api.compileTranscript).mockReset()
  })

  it("loadTranscript seeds the sliders from the embedded settings", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue(transcript() as never)
    const store = useTranscribeStore()
    await store.loadTranscript("t1")
    const { cosineDistThreshold, separationMin } = useMatchingThresholds()
    expect(cosineDistThreshold.value).toBe(0.3)
    expect(separationMin.value).toBe(0.1)
  })

  it("recompile posts the settings and replaces the active transcript", async () => {
    const store = useTranscribeStore()
    store.jobs.push(job())
    store.activeJobId = "t1"
    const next = transcript({ settings: { cosine_dist_threshold: 0.2, separation_min: 0.5, quality_min: 0, confidence_min: 0 } })
    vi.mocked(api.compileTranscript).mockResolvedValue(next as never)

    await store.recompile("t1", next.settings)

    expect(api.compileTranscript).toHaveBeenCalledWith("t1", next.settings)
    expect(store.activeTranscript).toEqual(next)
    expect(useMatchingThresholds().separationMin.value).toBe(0.5)
  })
})

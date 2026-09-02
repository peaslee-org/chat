import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  rerunJob: vi.fn(),
  fetchTurnDistances: vi.fn(),
  getJobAudioUrl: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import RunDetailView from "../RunDetailView.vue"
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

function mountWithJob(j: TranscriptionJob) {
  setActivePinia(createPinia())
  const store = useTranscribeStore()
  store.jobs.push(j)
  store.activeJobId = j.job_id
  const w = mount(RunDetailView, { props: { showNewJobForm: false } })
  return { store, w }
}

describe("RunDetailView — input audio row", () => {
  beforeEach(() => {
    vi.mocked(api.fetchTurnDistances).mockReset().mockResolvedValue({ turns: [] })
    vi.mocked(api.getJobAudioUrl).mockReset()
  })

  it("fetches and renders a player + download link for a complete job", async () => {
    vi.mocked(api.getJobAudioUrl).mockResolvedValue({
      url: "https://dl/audio/j/source",
      download_url: "https://dl/audio/j/source?dl=job-audio",
      filename: "job-audio",
      expires_at: "2099-01-01T00:00:00Z",
    })
    const { w } = mountWithJob(job({ status: "complete" }))
    await flushPromises()

    expect(api.getJobAudioUrl).toHaveBeenCalledWith("t1")
    const audioEl = w.find("audio")
    expect(audioEl.exists()).toBe(true)
    expect(audioEl.attributes("src")).toBe("https://dl/audio/j/source")
    expect(audioEl.attributes("controls")).toBeDefined()
    const downloadLink = w.findAll("a").find(a => a.text() === "Download")
    expect(downloadLink?.attributes("href")).toBe("https://dl/audio/j/source?dl=job-audio")
  })

  it("fetches and renders a player for a failed job too", async () => {
    vi.mocked(api.getJobAudioUrl).mockResolvedValue({
      url: "https://dl/audio/j/source",
      download_url: "https://dl/audio/j/source?dl=job-audio",
      filename: "job-audio",
      expires_at: "2099-01-01T00:00:00Z",
    })
    const { w } = mountWithJob(job({ status: "failed", error_message: "boom" }))
    await flushPromises()

    expect(api.getJobAudioUrl).toHaveBeenCalledWith("t1")
    expect(w.find("audio").exists()).toBe(true)
  })

  it("does not fetch audio for a non-terminal (in-progress) job", async () => {
    const { w } = mountWithJob(job({ status: "transcribing" }))
    await flushPromises()

    expect(api.getJobAudioUrl).not.toHaveBeenCalled()
    expect(w.find("audio").exists()).toBe(false)
  })

  it("shows a quiet expired note (no player) when the API 404s", async () => {
    const err = Object.assign(new Error("not found"), { response: { status: 404 } })
    vi.mocked(api.getJobAudioUrl).mockRejectedValue(err)
    const { w } = mountWithJob(job({ status: "complete" }))
    await flushPromises()

    expect(w.find("audio").exists()).toBe(false)
    expect(w.text()).toContain("Input audio expired")
  })
})

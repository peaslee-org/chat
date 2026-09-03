import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  rerunJob: vi.fn(),
  fetchTurnDistances: vi.fn(),
  getJobAudioUrl: vi.fn(),
  getTranscript: vi.fn(),
  compileTranscript: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import RunDetailView from "../RunDetailView.vue"
import { useTranscribeStore } from "@/stores/transcribe"
import { seedThresholds, useMatchingThresholds } from "@/composables/useMatchingThresholds"
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
    expect(downloadLink?.exists()).toBe(true)
  })

  it("re-resolves the download URL through the store at click time, rather than using a captured href", async () => {
    // The panel-open fetch returns an entry within 30s of expiry, so the store's cache treats
    // it as stale and the click handler's fetchJobAudioUrl call hits the API again — proving
    // the download goes through the store's re-resolve path instead of a captured href.
    const almostExpired = new Date(Date.now() + 10_000).toISOString()
    vi.mocked(api.getJobAudioUrl)
      .mockResolvedValueOnce({
        url: "https://dl/audio/j/source",
        download_url: "https://dl/audio/j/source?dl=stale",
        filename: "job-audio",
        expires_at: almostExpired,
      })
      .mockResolvedValueOnce({
        url: "https://dl/audio/j/source",
        download_url: "https://dl/audio/j/source?dl=fresh",
        filename: "job-audio",
        expires_at: "2099-01-01T00:00:00Z",
      })
    // jsdom's window.location.assign isn't configurable enough for vi.spyOn — swap the whole
    // `location` property for a stub with a mockable `assign`, then restore it.
    const originalLocation = window.location
    const assignMock = vi.fn()
    Object.defineProperty(window, "location", { configurable: true, value: { assign: assignMock } })
    try {
      const { w } = mountWithJob(job({ status: "complete" }))
      await flushPromises()

      const downloadLink = w.findAll("a").find(a => a.text() === "Download")
      expect(downloadLink?.attributes("href")).toBe("#")
      await downloadLink!.trigger("click")
      await flushPromises()

      expect(api.getJobAudioUrl).toHaveBeenCalledTimes(2) // once on open, once at click time
      expect(assignMock).toHaveBeenCalledWith("https://dl/audio/j/source?dl=fresh")
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: originalLocation })
    }
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
    const err = Object.assign(new Error("not found"), { isAxiosError: true, response: { status: 404 } })
    vi.mocked(api.getJobAudioUrl).mockRejectedValue(err)
    const { w } = mountWithJob(job({ status: "complete" }))
    await flushPromises()

    expect(w.find("audio").exists()).toBe(false)
    expect(w.text()).toContain("Input audio expired")
  })

  it("shows a neutral error note (not 'expired') for a non-404 failure", async () => {
    const err = Object.assign(new Error("network error"), { isAxiosError: true, response: { status: 500 } })
    vi.mocked(api.getJobAudioUrl).mockRejectedValue(err)
    const { w } = mountWithJob(job({ status: "complete" }))
    await flushPromises()

    expect(w.find("audio").exists()).toBe(false)
    expect(w.text()).toContain("Couldn't load input audio")
    expect(w.text()).not.toContain("Input audio expired")
  })
})

describe("RunDetailView — compiled transcript display", () => {
  const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 }

  beforeEach(() => {
    vi.mocked(api.fetchTurnDistances).mockReset().mockResolvedValue({
      turns: [{ start_time: 0, end_time: 1, text: "a", candidates: [{ candidate_id: "c1", speaker_name: "Jane", cosine_dist: 0.9 }] }],
    })
  })

  it("renders the stored turns, not the local preview, when sliders equal the embedded settings", async () => {
    const { store, w } = mountWithJob(job())
    store.activeTranscript = {
      segments: [],
      turns: [{ start_time: 0, end_time: 1, text: "a", label: "Stored", match_type: "high" }],
      settings, compiled_at: "2026-09-03T12:00:00Z",
    }
    seedThresholds(settings)
    await flushPromises()
    expect(w.text()).toContain("Stored")
    expect(w.text()).not.toContain("Unknown")
  })

  it("switches to the local preview once a slider differs", async () => {
    const { store, w } = mountWithJob(job())
    store.activeTranscript = {
      segments: [],
      turns: [{ start_time: 0, end_time: 1, text: "a", label: "Stored", match_type: "high" }],
      settings, compiled_at: "2026-09-03T12:00:00Z",
    }
    seedThresholds(settings)
    await flushPromises()
    useMatchingThresholds().cosineDistThreshold.value = 0.95   // 0.9 now within threshold → "Jane"
    await flushPromises()
    expect(w.text()).toContain("Jane")
    expect(w.text()).not.toContain("Stored")
  })
})

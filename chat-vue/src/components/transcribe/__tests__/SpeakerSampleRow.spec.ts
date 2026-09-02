import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  getSampleAudioUrl: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import SpeakerSampleRow from "../SpeakerSampleRow.vue"
import type { SpeakerSample } from "@/types"

function sample(overrides: Partial<SpeakerSample> = {}): SpeakerSample {
  return {
    sample_id: "sm1",
    status: "ready",
    duration_seconds: 12.3,
    error_message: null,
    created_at: "2026-08-29T10:00:00Z",
    ...overrides,
  }
}

function mountRow(s: SpeakerSample) {
  setActivePinia(createPinia())
  return mount(SpeakerSampleRow, {
    props: { sample: s, speakerId: "sp1", speakerName: "Barry" },
  })
}

describe("SpeakerSampleRow — play affordance", () => {
  beforeEach(() => {
    vi.mocked(api.getSampleAudioUrl).mockReset()
  })

  it("shows a play affordance for a ready sample", () => {
    const w = mountRow(sample({ status: "ready" }))
    const btn = w.find('[data-testid="play-sample"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes("type")).toBe("button")
    expect(btn.attributes("aria-label")).toBe("Play sample audio")
  })

  it("updates the play affordance's aria-label once the player is open", async () => {
    vi.mocked(api.getSampleAudioUrl).mockResolvedValue({
      url: "https://dl/audio/sp1/samples/sm1",
      download_url: "https://dl/audio/sp1/samples/sm1?dl=speaker-sample",
      filename: "speaker-sample",
      expires_at: "2099-01-01T00:00:00Z",
    })
    const w = mountRow(sample({ status: "ready" }))
    await w.find('[data-testid="play-sample"]').trigger("click")
    await flushPromises()
    expect(w.find('[data-testid="play-sample"]').attributes("aria-label")).toBe("Hide sample audio")
  })

  it("shows no play affordance for a processing sample", () => {
    const w = mountRow(sample({ status: "processing" }))
    expect(w.find('[data-testid="play-sample"]').exists()).toBe(false)
  })

  it("shows no play affordance for a failed sample", () => {
    const w = mountRow(sample({ status: "failed" }))
    expect(w.find('[data-testid="play-sample"]').exists()).toBe(false)
  })

  it("fetches the presigned URL on first use and renders a player + download link", async () => {
    vi.mocked(api.getSampleAudioUrl).mockResolvedValue({
      url: "https://dl/audio/sp1/samples/sm1",
      download_url: "https://dl/audio/sp1/samples/sm1?dl=speaker-sample",
      filename: "speaker-sample",
      expires_at: "2099-01-01T00:00:00Z",
    })
    const w = mountRow(sample({ status: "ready" }))

    expect(w.find("audio").exists()).toBe(false)
    await w.find('[data-testid="play-sample"]').trigger("click")
    await flushPromises()

    expect(api.getSampleAudioUrl).toHaveBeenCalledWith("sp1", "sm1")
    const audioEl = w.find("audio")
    expect(audioEl.exists()).toBe(true)
    expect(audioEl.attributes("src")).toBe("https://dl/audio/sp1/samples/sm1")
    const downloadLink = w.findAll("a").find(a => a.text() === "Download")
    expect(downloadLink?.exists()).toBe(true)
  })

  it("re-resolves the download URL through the store at click time, rather than using a captured href", async () => {
    // Panel-open fetch returns an entry within 30s of expiry so the store treats it as stale,
    // forcing the download click's fetchSampleAudioUrl call to hit the API again.
    const almostExpired = new Date(Date.now() + 10_000).toISOString()
    vi.mocked(api.getSampleAudioUrl)
      .mockResolvedValueOnce({
        url: "https://dl/audio/sp1/samples/sm1",
        download_url: "https://dl/audio/sp1/samples/sm1?dl=stale",
        filename: "speaker-sample",
        expires_at: almostExpired,
      })
      .mockResolvedValueOnce({
        url: "https://dl/audio/sp1/samples/sm1",
        download_url: "https://dl/audio/sp1/samples/sm1?dl=fresh",
        filename: "speaker-sample",
        expires_at: "2099-01-01T00:00:00Z",
      })
    const originalLocation = window.location
    const assignMock = vi.fn()
    Object.defineProperty(window, "location", { configurable: true, value: { assign: assignMock } })
    try {
      const w = mountRow(sample({ status: "ready" }))
      await w.find('[data-testid="play-sample"]').trigger("click")
      await flushPromises()

      const downloadLink = w.findAll("a").find(a => a.text() === "Download")
      expect(downloadLink?.attributes("href")).toBe("#")
      await downloadLink!.trigger("click")
      await flushPromises()

      expect(api.getSampleAudioUrl).toHaveBeenCalledTimes(2) // once on play, once at download click
      expect(assignMock).toHaveBeenCalledWith("https://dl/audio/sp1/samples/sm1?dl=fresh")
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: originalLocation })
    }
  })

  it("shows the error copy and does not navigate when the click-time fetch fails", async () => {
    // First fetch returns an entry within 30s of expiry so the store treats it as stale,
    // forcing the download click to hit the API again — where it then rejects.
    const almostExpired = new Date(Date.now() + 10_000).toISOString()
    vi.mocked(api.getSampleAudioUrl)
      .mockResolvedValueOnce({
        url: "https://dl/audio/sp1/samples/sm1",
        download_url: "https://dl/audio/sp1/samples/sm1?dl=speaker-sample",
        filename: "speaker-sample",
        expires_at: almostExpired,
      })
      .mockRejectedValueOnce(new Error("expired"))
    const originalLocation = window.location
    const assignMock = vi.fn()
    Object.defineProperty(window, "location", { configurable: true, value: { assign: assignMock } })
    try {
      const w = mountRow(sample({ status: "ready" }))
      await w.find('[data-testid="play-sample"]').trigger("click")
      await flushPromises()

      const downloadLink = w.findAll("a").find(a => a.text() === "Download")
      await downloadLink!.trigger("click")
      await flushPromises()

      expect(w.text()).toContain("Couldn't load audio")
      expect(assignMock).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: originalLocation })
    }
  })

  it("does not refetch on a second click (cached by the store)", async () => {
    vi.mocked(api.getSampleAudioUrl).mockResolvedValue({
      url: "https://dl/audio/sp1/samples/sm1",
      download_url: "https://dl/audio/sp1/samples/sm1?dl=speaker-sample",
      filename: "speaker-sample",
      expires_at: "2099-01-01T00:00:00Z",
    })
    const w = mountRow(sample({ status: "ready" }))

    await w.find('[data-testid="play-sample"]').trigger("click")
    await flushPromises()
    await w.find('[data-testid="play-sample"]').trigger("click") // hide
    await w.find('[data-testid="play-sample"]').trigger("click") // show again
    await flushPromises()

    expect(api.getSampleAudioUrl).toHaveBeenCalledTimes(1)
  })

  it("still emits delete", async () => {
    const w = mountRow(sample())
    await w.find("button:last-of-type").trigger("click")
    expect(w.emitted("delete")).toBeTruthy()
  })
})

import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  rerunJob: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import TranscribeJobCard from "../TranscribeJobCard.vue"
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

function mountCard(j: TranscriptionJob) {
  return mount(TranscribeJobCard, {
    props: { job: j, isActive: false },
  })
}

describe("TranscribeJobCard — Re-run button", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.rerunJob).mockReset()
  })

  it.each(["complete", "failed"] as const)("shows Re-run for a %s job", (status) => {
    const wrapper = mountCard(job({ status }))
    expect(wrapper.text()).toContain("Re-run")
  })

  it.each(["pending", "transcribing", "matching"] as const)("hides Re-run for a %s job", (status) => {
    const wrapper = mountCard(job({ status }))
    expect(wrapper.text()).not.toContain("Re-run")
  })

  it("calls store.rerunJob with the job id when clicked, without also selecting the job", async () => {
    vi.mocked(api.rerunJob).mockResolvedValue(job({ job_id: "t2", status: "transcribing" }))
    const wrapper = mountCard(job({ job_id: "t1", status: "failed" }))
    const store = useTranscribeStore()
    const selectSpy = vi.spyOn(store, "selectJob")

    await wrapper.find("button[data-testid='rerun-button']").trigger("click")
    await Promise.resolve()
    await Promise.resolve()

    expect(api.rerunJob).toHaveBeenCalledWith("t1")
    // clicking Re-run must not also trigger the card's own click-to-select handler
    expect(selectSpy).not.toHaveBeenCalledWith("t1")
  })
})

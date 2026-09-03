import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import TranscriptDisplay, { transcriptText } from "../TranscriptDisplay.vue"

const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0.1, confidence_min: 0 }
const turns = [{ start_time: 0.03, end_time: 7.62, text: "Hi", label: "Jane", matchType: "high" as const }]

describe("transcriptText", () => {
  it("writes a settings header then the turn lines with the tier", () => {
    const text = transcriptText(turns, [], settings, "2026-09-03T12:00:00Z")
    expect(text.split("\n")).toEqual([
      "# compiled 2026-09-03T12:00:00Z  cosine<=0.25  separation>=0.00  quality>=0.10  confidence>=0.00",
      "[0.03 - 7.62] Jane [high]: Hi",
    ])
  })

  it("marks an uncompiled preview in the header", () => {
    const text = transcriptText(turns, [], settings, null)
    expect(text.startsWith("# preview (not compiled)  cosine<=0.25")).toBe(true)
  })

  it("falls back to segment lines with no header when there are no turns", () => {
    const seg = { segment_id: "s", anonymous_label: "PROBABLY_Jane", speaker_name: null, start_time: 0.21, end_time: 7.68, text: "Hi" }
    expect(transcriptText([], [seg])).toBe("[0.21 - 7.68] PROBABLY_Jane: Hi")
  })
})

describe("TranscriptDisplay", () => {
  it("renders dynamic mode when computed turns are given", () => {
    const w = mount(TranscriptDisplay, {
      props: { transcript: { segments: [], turns: null, settings, compiled_at: null }, computedTurns: turns },
    })
    expect(w.text()).toContain("Jane")
  })
})

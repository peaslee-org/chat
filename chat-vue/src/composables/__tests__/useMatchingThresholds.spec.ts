import { describe, expect, it } from "vitest"
import cases from "../../../../chat-api/tests/fixtures/compile_turns_cases.json"
import {
  computeTurns,
  compiledToComputed,
  currentSettings,
  seedThresholds,
  settingsDiffer,
  useMatchingThresholds,
} from "../useMatchingThresholds"
import type { CompiledTurn, TurnDistanceData } from "@/types"

describe("computeTurns agrees with the API's compile_turns", () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const s = c.settings
      const out = computeTurns(c.turns as TurnDistanceData[], s.cosine_dist_threshold, s.separation_min, s.quality_min, s.confidence_min)
      expect(out.map(({ matchType, ...rest }) => ({ ...rest, match_type: matchType }))).toEqual(c.expected)
    })
  }
})

describe("threshold seeding", () => {
  it("seeds the sliders and reports no difference afterwards", () => {
    const s = { cosine_dist_threshold: 0.3, separation_min: 0.1, quality_min: 0.2, confidence_min: 0.05 }
    seedThresholds(s)
    const { cosineDistThreshold, separationMin } = useMatchingThresholds()
    expect(cosineDistThreshold.value).toBe(0.3)
    expect(separationMin.value).toBe(0.1)
    expect(currentSettings()).toEqual(s)
    expect(settingsDiffer(s)).toBe(false)
    cosineDistThreshold.value = 0.31
    expect(settingsDiffer(s)).toBe(true)
  })
})

describe("compiledToComputed", () => {
  it("maps match_type to matchType", () => {
    const turns: CompiledTurn[] = [{ start_time: 0, end_time: 1, text: "a", label: "Jane", match_type: "high" }]
    expect(compiledToComputed(turns)).toEqual([{ start_time: 0, end_time: 1, text: "a", label: "Jane", matchType: "high" }])
  })
})

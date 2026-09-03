import { ref } from "vue"
import type { CompiledTurn, CompileSettings, MatchType, TurnDistanceData } from "@/types"

export type { MatchType }

export interface ComputedTurn {
  start_time: number
  end_time: number
  text: string
  label: string
  matchType: MatchType
}

// Module-level singleton — shared across all component instances
const cosineDistThreshold = ref(0.25)
const separationMin = ref(0.0)
const qualityMin = ref(0.0)
const confidenceMin = ref(0.0)

export function useMatchingThresholds() {
  return { cosineDistThreshold, separationMin, qualityMin, confidenceMin }
}

export const DEFAULT_COMPILE_SETTINGS: CompileSettings = {
  cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0,
}

/** Set the sliders to a transcript's embedded settings (called whenever a transcript loads). */
export function seedThresholds(s: CompileSettings): void {
  cosineDistThreshold.value = s.cosine_dist_threshold
  separationMin.value = s.separation_min
  qualityMin.value = s.quality_min
  confidenceMin.value = s.confidence_min
}

export function currentSettings(): CompileSettings {
  return {
    cosine_dist_threshold: cosineDistThreshold.value,
    separation_min: separationMin.value,
    quality_min: qualityMin.value,
    confidence_min: confidenceMin.value,
  }
}

const EPS = 1e-9
export function settingsDiffer(s: CompileSettings): boolean {
  const c = currentSettings()
  return (Object.keys(s) as (keyof CompileSettings)[]).some(k => Math.abs(c[k] - s[k]) > EPS)
}

export function compiledToComputed(turns: CompiledTurn[]): ComputedTurn[] {
  return turns.map(({ match_type, ...rest }) => ({ ...rest, matchType: match_type }))
}

// Mirrors compile_turns in chat-api/app/services/transcript_compiler.py; both run chat-api/tests/fixtures/compile_turns_cases.json.
export function computeTurns(
  turns: TurnDistanceData[],
  threshold: number,
  sepMin: number,
  qualMin: number,
  confMin: number,
): ComputedTurn[] {
  return turns.map(turn => {
    const sorted = [...turn.candidates].sort((a, b) => a.cosine_dist - b.cosine_dist)
    if (sorted.length === 0) {
      return { start_time: turn.start_time, end_time: turn.end_time, text: turn.text, label: "Unknown", matchType: "none" }
    }
    const best = sorted[0]

    // High: passes cosine distance test
    if (best.cosine_dist <= threshold) {
      return {
        start_time: turn.start_time, end_time: turn.end_time, text: turn.text,
        label: best.speaker_name ?? "Unknown",
        matchType: "high",
      }
    }

    if (sorted.length >= 2) {
      const runnerUp = sorted[1]
      if (runnerUp.cosine_dist > best.cosine_dist) {
        const separation = 1 - best.cosine_dist / runnerUp.cosine_dist
        const quality = threshold / best.cosine_dist
        const confidence = separation * quality

        // Medium: fails cosine but passes all of sep/qual/conf
        if (separation >= sepMin && quality >= qualMin && confidence >= confMin) {
          return {
            start_time: turn.start_time, end_time: turn.end_time, text: turn.text,
            label: best.speaker_name ?? "Unknown",
            matchType: "medium",
          }
        }

        // Low: fails cosine + quality/confidence but passes separation
        if (separation >= sepMin) {
          return {
            start_time: turn.start_time, end_time: turn.end_time, text: turn.text,
            label: best.speaker_name ?? "Unknown",
            matchType: "low",
          }
        }
      }
    }

    return { start_time: turn.start_time, end_time: turn.end_time, text: turn.text, label: "Unknown", matchType: "none" }
  })
}

// Fixed palette — distinct hues, high contrast on white
const SPEAKER_COLORS = [
  "text-blue-700",
  "text-red-600",
  "text-green-700",
  "text-purple-700",
  "text-orange-600",
  "text-pink-600",
  "text-teal-700",
  "text-amber-700",
]

export function speakerColor(label: string, allLabels: string[]): string {
  if (label === "Unknown") return "text-gray-400"
  const knownSpeakers = [...new Set(allLabels.filter(l => l !== "Unknown"))].sort()
  const idx = knownSpeakers.indexOf(label)
  if (idx === -1) return "text-gray-400"
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length]
}

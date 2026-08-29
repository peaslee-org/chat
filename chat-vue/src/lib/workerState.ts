import type { WorkerState } from "@/types"

/** `waitSeconds` is the *remaining* wait while starting (the API subtracts elapsed time). */
export function workerStateLabel(state: WorkerState | undefined, waitSeconds = 0): string {
  switch (state) {
    case "running": return "GPU ready"
    case "starting": return `GPU starting · ~${Math.max(1, Math.round(waitSeconds / 60))} min left`
    default: return "GPU off — starts on your next job"
  }
}

/** Seconds since the worker task was launched, as m:ss. */
export function elapsedLabel(startingSince: string, now: Date): string {
  const s = Math.max(0, Math.floor((now.getTime() - new Date(startingSince).getTime()) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

/** 380 → "6m20s"; used for startup promises/actuals in the usage panel. */
export function durationLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`
}

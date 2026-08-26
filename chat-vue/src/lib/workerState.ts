import type { WorkerState } from "@/types"

export function workerStateLabel(state: WorkerState | undefined, waitSeconds = 0): string {
  switch (state) {
    case "running": return "GPU ready"
    case "starting": return `GPU starting · ~${Math.max(1, Math.round(waitSeconds / 60))} min`
    default: return "GPU off — starts on your next job"
  }
}

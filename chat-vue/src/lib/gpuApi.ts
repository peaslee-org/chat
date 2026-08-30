import { apiClient } from "@/lib/axios"
import type { GpuFamily, GpuState, GpuUsage } from "@/types"

export async function getGpuState(family: GpuFamily = "transcription"): Promise<GpuState> {
  return (await apiClient.get("/api/v1/gpu/state", { params: { family } })).data
}
export async function warmGpu(family: GpuFamily = "transcription"): Promise<GpuState> {
  return (await apiClient.post("/api/v1/gpu/warm", null, { params: { family } })).data
}
/** Budget/session figures are shared across families; the medians and caps are the family's. */
export async function getGpuUsage(family: GpuFamily = "transcription"): Promise<GpuUsage> {
  return (await apiClient.get("/api/v1/gpu/usage", { params: { family } })).data
}

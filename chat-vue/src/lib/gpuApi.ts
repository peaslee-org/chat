import { apiClient } from "@/lib/axios"
import type { GpuState, GpuUsage } from "@/types"

export async function getGpuState(): Promise<GpuState> {
  return (await apiClient.get("/api/v1/gpu/state")).data
}
export async function warmGpu(): Promise<GpuState> {
  return (await apiClient.post("/api/v1/gpu/warm")).data
}
export async function getGpuUsage(): Promise<GpuUsage> {
  return (await apiClient.get("/api/v1/gpu/usage")).data
}

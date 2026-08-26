import { apiClient } from "@/lib/axios"
import type {
  MeshUrlResponse,
  PhotogrammetryJob,
  PhotogrammetryJobCreateResponse,
  PhotogrammetryJobListResponse,
} from "@/types"

export { uploadToS3 } from "@/lib/transcribeApi"

const BASE = "/api/v1/photogrammetry"

export async function createJob(name: string | null, filenames: string[]): Promise<PhotogrammetryJobCreateResponse> {
  const res = await apiClient.post(`${BASE}/jobs`, { name, filenames })
  return res.data
}

export async function confirmJob(jobId: string): Promise<void> {
  await apiClient.post(`${BASE}/jobs/${jobId}/confirm`)
}

export async function listJobs(cursor?: string): Promise<PhotogrammetryJobListResponse> {
  const res = await apiClient.get(`${BASE}/jobs`, { params: { cursor, limit: 20 } })
  return res.data
}

export async function getJob(jobId: string): Promise<PhotogrammetryJob> {
  const res = await apiClient.get(`${BASE}/jobs/${jobId}`)
  return res.data
}

export async function deleteJob(jobId: string): Promise<void> {
  await apiClient.delete(`${BASE}/jobs/${jobId}`)
}

export async function createSampleJob(): Promise<{ job_id: string }> {
  const res = await apiClient.post(`${BASE}/jobs/sample`)
  return res.data
}

export async function getMeshUrl(jobId: string): Promise<MeshUrlResponse> {
  const res = await apiClient.get(`${BASE}/jobs/${jobId}/mesh`)
  return res.data
}

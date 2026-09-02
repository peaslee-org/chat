import { apiClient } from "@/lib/axios"
import type {
  PublicConversationDetail,
  PublicScanDetail,
  PublicTranscriptionDetail,
  ShowcaseResponse,
} from "@/types"

const BASE = "/api/v1/public"

export async function getShowcase(): Promise<ShowcaseResponse> {
  return (await apiClient.get(`${BASE}/showcase`)).data
}

export async function getPublicScan(jobId: string): Promise<PublicScanDetail> {
  return (await apiClient.get(`${BASE}/photogrammetry/${jobId}`)).data
}

export async function getPublicTranscription(jobId: string): Promise<PublicTranscriptionDetail> {
  return (await apiClient.get(`${BASE}/transcriptions/${jobId}`)).data
}

export async function getPublicConversation(id: string): Promise<PublicConversationDetail> {
  return (await apiClient.get(`${BASE}/conversations/${id}`)).data
}

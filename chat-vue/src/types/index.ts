// Mirrors ModelOut from app/schemas/models.py
export interface Model {
  model_id: string
  model_name: string
  provider_name: string
  input_price_per_1k_tokens: number | null
  output_price_per_1k_tokens: number | null
}

// Mirrors ConversationOut from app/schemas/conversation.py
export interface Conversation {
  id: string
  title: string | null
  model_id: string | null
  input_price_per_1k_tokens: number | null
  output_price_per_1k_tokens: number | null
  created_at: string
  updated_at: string
  messages: Message[]
}

// Mirrors ChatRequest from app/schemas/chat.py
export interface ChatRequest {
  conversation_id?: string
  message: string
  model_id?: string
  input_price_per_1k_tokens?: number | null
  output_price_per_1k_tokens?: number | null
}

// Mirrors ChatResponse from app/schemas/chat.py
export interface ChatResponse {
  conversation_id: string
  reply: string
}

// Local UI-only type for displaying a message in the chat thread
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

// Mirrors MessageOut from app/schemas/conversation.py
export interface ApiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

// ── Speaker profiles ──────────────────────────────────────────────────────

export interface SpeakerProfile {
  speaker_id: string
  speaker_name: string | null
  created_at: string
  samples: SpeakerSample[]
}

export interface SpeakerSample {
  sample_id: string
  status: 'processing' | 'ready' | 'failed'
  duration_seconds: number | null
  error_message: string | null
  created_at: string
}

export interface SpeakerListResponse {
  items: SpeakerProfile[]
  next_cursor: string | null
}

export interface SampleUploadInitResponse {
  sample_id: string
  upload_url: string
}

// ── Transcription jobs ────────────────────────────────────────────────────

export interface TranscriptionJob {
  job_id: string
  status: 'pending' | 'transcribing' | 'matching' | 'complete' | 'failed'
  speaker_count_hint: number
  language: string
  speaker_ids: string[]
  error_message: string | null
  partial_transcript_available: boolean
  matched_speaker_count: number | null
  total_segment_count: number | null
  created_at: string
  updated_at: string
  completed_at: string | null
  worker_state?: WorkerState | null
  estimated_wait_seconds?: number
  gpu_notice?: string | null
}

export type WorkerState = 'off' | 'starting' | 'running'

export type GpuFamily = "transcription" | "photogrammetry"

export interface GpuState {
  worker_state: WorkerState
  estimated_wait_seconds: number
  warm_until: string | null
  notice: string | null
}

export interface GpuSessionSummary {
  started_at: string; ended_at: string | null; reason: string; started_by: string
  end_reason: string | null; hours: number; family: GpuFamily
}

export interface GpuUsage {
  today_hours: number; month_hours: number; daily_cap_hours: number; monthly_cap_hours: number
  warms_today_for_user: number; warm_cap_per_user_per_day: number
  estimated_month_cost_usd: number; hourly_rate_usd: number
  actual_month_to_date_usd: number | null; actual_fetched_at: string | null
  sessions: GpuSessionSummary[]
}

export interface JobListResponse {
  items: TranscriptionJob[]
  next_cursor: string | null
}

export interface JobCreateRequest {
  speaker_count_hint?: number
  speaker_ids?: string[]
  language?: string
}

export interface JobCreateResponse {
  job_id: string
  upload_url: string
}

// ── Job activity log ──────────────────────────────────────────────────────

export interface JobLogEntry {
  ts: string
  direction: 'request' | 'response'
  label: string
  detail?: string
  error?: boolean
}

// ── Transcript ────────────────────────────────────────────────────────────

export interface TranscriptSegment {
  segment_id: string
  anonymous_label: string
  speaker_name: string | null
  start_time: number
  end_time: number
  text: string
}

export interface TranscriptResponse {
  segments: TranscriptSegment[]
}

// ── Turn distances (client-side matching analysis) ────────────────────────

export interface TurnCandidate {
  candidate_id: string
  speaker_name: string | null
  cosine_dist: number
}

export interface TurnDistanceData {
  start_time: number
  end_time: number
  text: string
  candidates: TurnCandidate[]
}

export interface TurnDistancesResponse {
  turns: TurnDistanceData[]
}

// ── Photogrammetry ────────────────────────────────────────────────────────

export type PhotogrammetryJobStatus = 'pending' | 'queued' | 'processing' | 'complete' | 'failed'
export type PhotogrammetryStage = 'sfm' | 'dense' | 'mesh' | 'texture'

export interface PhotogrammetryJob {
  job_id: string
  name: string
  status: PhotogrammetryJobStatus
  stage: PhotogrammetryStage | null
  image_count: number
  preview_url: string | null
  error_message: string | null
  mock: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
  worker_state?: WorkerState | null
  estimated_wait_seconds?: number | null
  gpu_notice?: string | null
}

export interface UploadTarget {
  filename: string
  key: string
  url: string
}

export interface PhotogrammetryJobCreateResponse {
  job_id: string
  uploads: UploadTarget[]
}

export interface PhotogrammetryJobListResponse {
  items: PhotogrammetryJob[]
  next_cursor: string | null
}

export interface MeshUrlResponse {
  url: string                           // plain GET, for <model-viewer>
  download_url: string                  // same GLB, served as an attachment
  preview_download_url: string | null   // preview.png as an attachment, when it exists
  expires_at: string
}

/** Store-side cache entry for MeshUrlResponse (camelCase, epoch-ms expiry). */
export interface MeshUrls {
  url: string
  downloadUrl: string
  previewDownloadUrl: string | null
  expiresAt: number
}

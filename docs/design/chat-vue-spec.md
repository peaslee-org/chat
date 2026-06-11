# Audio Transcription — chat-vue Implementation Spec

**Based on:** `audio_transcription_spec.md` v1.1
**Project:** `chat-vue/` (Vue 3, TypeScript, Tailwind CSS, Vite)
**Status:** Draft

---

## Overview

This document specifies every file to create or modify in `chat-vue/src/` to implement the transcription UI. The feature lives at a new route `/transcribe` and follows the existing layered pattern: **router → view → components → store → lib/axios → API**.

The UI has two panels:
- **Left:** Speaker profile management (create profiles, upload reference samples)
- **Right:** Transcription jobs (submit audio, track status, view transcripts)

---

## New Route

Add to `router/index.ts`:

```typescript
{
  path: "/transcribe",
  name: "transcribe",
  component: () => import("@/views/TranscribeView.vue"),
  meta: { requiresAuth: true },
}
```

The existing route guard already redirects unauthenticated users; `meta: { requiresAuth: true }` hooks into the same check.

---

## Navigation

Modify `components/ConversationSidebar.vue` to add a nav toggle at the top of the sidebar. Add two icon links — Chat and Transcribe — using `RouterLink`. The active link is highlighted with Tailwind's active class.

```html
<!-- At the top of ConversationSidebar.vue, above the conversation list -->
<nav class="flex border-b border-gray-200 mb-2">
  <RouterLink
    to="/"
    class="flex-1 py-2 text-center text-sm font-medium"
    :class="$route.path === '/' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500 hover:text-gray-700'"
  >
    Chat
  </RouterLink>
  <RouterLink
    to="/transcribe"
    class="flex-1 py-2 text-center text-sm font-medium"
    :class="$route.path.startsWith('/transcribe') ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500 hover:text-gray-700'"
  >
    Transcribe
  </RouterLink>
</nav>
```

---

## TypeScript Types (`src/types/index.ts`)

Append to the existing file. These mirror the backend Pydantic schemas.

```typescript
// ── Speaker profiles ──────────────────────────────────────────────────────

export interface SpeakerProfile {
  speaker_id: string
  speaker_name: string
  created_at: string
  samples: SpeakerSample[]
}

export interface SpeakerSample {
  sample_id: string
  status: 'processing' | 'ready' | 'failed'
  duration_seconds: number | null
  created_at: string
}

export interface SpeakerListResponse {
  items: SpeakerProfile[]
  next_cursor: string | null
}

export interface SampleUploadInitResponse {
  sample_id: string
  upload_url: string         // pre-signed POST URL
  upload_fields: Record<string, string>  // pre-signed POST policy fields
}

// ── Transcription jobs ────────────────────────────────────────────────────

export interface TranscriptionJob {
  job_id: string
  status: 'pending' | 'transcribing' | 'matching' | 'complete' | 'failed'
  speaker_count_hint: number
  language: string
  error_message: string | null
  partial_transcript_available: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
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
  upload_fields: Record<string, string>
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
  transcript_url: string | null
}
```

---

## API Client (`src/lib/transcribeApi.ts`)

New file — keeps transcription API calls separate from the general `apiClient`. Uses the same `apiClient` axios instance (auth header injected automatically).

```typescript
import apiClient from "@/lib/axios"
import type {
  SpeakerProfile, SpeakerListResponse, SampleUploadInitResponse,
  TranscriptionJob, JobListResponse, JobCreateRequest, JobCreateResponse,
  TranscriptResponse,
} from "@/types"

// ── Speakers ──────────────────────────────────────────────────────────────

export async function createSpeaker(name: string): Promise<SpeakerProfile> {
  const res = await apiClient.post("/api/v1/transcribe/speakers", { speaker_name: name })
  return res.data
}

export async function listSpeakers(cursor?: string): Promise<SpeakerListResponse> {
  const res = await apiClient.get("/api/v1/transcribe/speakers", {
    params: { cursor, limit: 50 },
  })
  return res.data
}

export async function deleteSpeaker(speakerId: string): Promise<void> {
  await apiClient.delete(`/api/v1/transcribe/speakers/${speakerId}`)
}

export async function initSampleUpload(speakerId: string): Promise<SampleUploadInitResponse> {
  const res = await apiClient.post(
    `/api/v1/transcribe/speakers/${speakerId}/samples`
  )
  return res.data
}

export async function confirmSampleUpload(
  speakerId: string,
  sampleId: string,
): Promise<void> {
  await apiClient.post(
    `/api/v1/transcribe/speakers/${speakerId}/samples/${sampleId}/confirm`
  )
}

export async function deleteSample(speakerId: string, sampleId: string): Promise<void> {
  await apiClient.delete(
    `/api/v1/transcribe/speakers/${speakerId}/samples/${sampleId}`
  )
}

// ── Jobs ──────────────────────────────────────────────────────────────────

export async function createJob(params: JobCreateRequest): Promise<JobCreateResponse> {
  const res = await apiClient.post("/api/v1/transcribe/jobs", params)
  return res.data
}

export async function confirmJobUpload(jobId: string): Promise<void> {
  await apiClient.post(`/api/v1/transcribe/jobs/${jobId}/confirm`)
}

export async function listJobs(cursor?: string): Promise<JobListResponse> {
  const res = await apiClient.get("/api/v1/transcribe/jobs", {
    params: { cursor, limit: 20 },
  })
  return res.data
}

export async function getJobStatus(jobId: string): Promise<TranscriptionJob> {
  const res = await apiClient.get(`/api/v1/transcribe/jobs/${jobId}`)
  return res.data
}

export async function getTranscript(jobId: string): Promise<TranscriptResponse> {
  const res = await apiClient.get(`/api/v1/transcribe/jobs/${jobId}/transcript`)
  return res.data
}

export async function deleteJob(jobId: string): Promise<void> {
  await apiClient.delete(`/api/v1/transcribe/jobs/${jobId}`)
}

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * Upload a file directly to S3 using a pre-signed POST URL.
 * Must NOT use apiClient — no Authorization header should be sent to S3.
 */
export async function uploadToS3(
  uploadUrl: string,
  fields: Record<string, string>,
  file: File,
): Promise<void> {
  const formData = new FormData()
  // Policy fields must come before the file
  for (const [key, value] of Object.entries(fields)) {
    formData.append(key, value)
  }
  formData.append("file", file)

  const res = await fetch(uploadUrl, { method: "POST", body: formData })
  if (!res.ok) {
    throw new Error(`S3 upload failed: ${res.status}`)
  }
}
```

---

## Pinia Store (`src/stores/transcribe.ts`)

```typescript
import { defineStore } from "pinia"
import { ref, computed } from "vue"
import * as api from "@/lib/transcribeApi"
import type { SpeakerProfile, TranscriptionJob, TranscriptResponse } from "@/types"

export const useTranscribeStore = defineStore("transcribe", () => {

  // ── State ─────────────────────────────────────────────────────────────

  const speakers = ref<SpeakerProfile[]>([])
  const speakerNextCursor = ref<string | null>(null)

  const jobs = ref<TranscriptionJob[]>([])
  const jobNextCursor = ref<string | null>(null)

  const activeJobId = ref<string | null>(null)
  const activeTranscript = ref<TranscriptResponse | null>(null)

  // job_id → interval ID (for polling cleanup)
  const pollingIntervals = ref<Map<string, ReturnType<typeof setInterval>>>(new Map())

  // ── Getters ───────────────────────────────────────────────────────────

  const activeJob = computed(() =>
    jobs.value.find(j => j.job_id === activeJobId.value) ?? null
  )

  const readySpeakers = computed(() =>
    speakers.value.filter(s => s.samples.some(sm => sm.status === "ready"))
  )

  // ── Speaker actions ───────────────────────────────────────────────────

  async function loadSpeakers(reset = false): Promise<void> {
    if (reset) { speakers.value = []; speakerNextCursor.value = null }
    const res = await api.listSpeakers(speakerNextCursor.value ?? undefined)
    speakers.value.push(...res.items)
    speakerNextCursor.value = res.next_cursor
  }

  async function createSpeaker(name: string): Promise<void> {
    const profile = await api.createSpeaker(name)
    speakers.value.unshift({ ...profile, samples: [] })
  }

  async function deleteSpeaker(speakerId: string): Promise<void> {
    await api.deleteSpeaker(speakerId)
    speakers.value = speakers.value.filter(s => s.speaker_id !== speakerId)
  }

  async function uploadSample(speakerId: string, file: File): Promise<void> {
    // 1. Initiate
    const { sample_id, upload_url, upload_fields } = await api.initSampleUpload(speakerId)
    // 2. Upload to S3 (no auth header)
    await api.uploadToS3(upload_url, upload_fields, file)
    // 3. Confirm
    await api.confirmSampleUpload(speakerId, sample_id)
    // 4. Add optimistic sample in 'processing' state
    const speaker = speakers.value.find(s => s.speaker_id === speakerId)
    if (speaker) {
      speaker.samples.push({
        sample_id,
        status: "processing",
        duration_seconds: null,
        created_at: new Date().toISOString(),
      })
    }
  }

  async function deleteSample(speakerId: string, sampleId: string): Promise<void> {
    await api.deleteSample(speakerId, sampleId)
    const speaker = speakers.value.find(s => s.speaker_id === speakerId)
    if (speaker) {
      speaker.samples = speaker.samples.filter(sm => sm.sample_id !== sampleId)
    }
  }

  // ── Job actions ───────────────────────────────────────────────────────

  async function loadJobs(reset = false): Promise<void> {
    if (reset) { jobs.value = []; jobNextCursor.value = null }
    const res = await api.listJobs(jobNextCursor.value ?? undefined)
    jobs.value.push(...res.items)
    jobNextCursor.value = res.next_cursor
  }

  async function submitJob(
    file: File,
    params: { speakerCountHint: number; speakerIds: string[]; language: string },
  ): Promise<string> {
    // 1. Create job record
    const { job_id, upload_url, upload_fields } = await api.createJob({
      speaker_count_hint: params.speakerCountHint,
      speaker_ids: params.speakerIds.length ? params.speakerIds : undefined,
      language: params.language,
    })
    // 2. Upload to S3
    await api.uploadToS3(upload_url, upload_fields, file)
    // 3. Confirm
    await api.confirmJobUpload(job_id)
    // 4. Add to local job list and start polling
    jobs.value.unshift({
      job_id,
      status: "transcribing",
      speaker_count_hint: params.speakerCountHint,
      language: params.language,
      error_message: null,
      partial_transcript_available: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    })
    startPolling(job_id)
    return job_id
  }

  async function selectJob(jobId: string): Promise<void> {
    activeJobId.value = jobId
    activeTranscript.value = null
    const job = jobs.value.find(j => j.job_id === jobId)
    if (job && (job.status === "complete" || job.partial_transcript_available)) {
      await loadTranscript(jobId)
    }
  }

  async function loadTranscript(jobId: string): Promise<void> {
    activeTranscript.value = await api.getTranscript(jobId)
  }

  async function deleteJob(jobId: string): Promise<void> {
    stopPolling(jobId)
    await api.deleteJob(jobId)
    jobs.value = jobs.value.filter(j => j.job_id !== jobId)
    if (activeJobId.value === jobId) {
      activeJobId.value = null
      activeTranscript.value = null
    }
  }

  // ── Polling ───────────────────────────────────────────────────────────

  function startPolling(jobId: string): void {
    if (pollingIntervals.value.has(jobId)) return
    const id = setInterval(async () => {
      const updated = await api.getJobStatus(jobId)
      const idx = jobs.value.findIndex(j => j.job_id === jobId)
      if (idx !== -1) jobs.value[idx] = updated
      if (updated.status === "complete" || updated.status === "failed") {
        stopPolling(jobId)
        // Auto-load transcript for the active job
        if (
          activeJobId.value === jobId &&
          (updated.status === "complete" || updated.partial_transcript_available)
        ) {
          await loadTranscript(jobId)
        }
      }
    }, 5000)
    pollingIntervals.value.set(jobId, id)
  }

  function stopPolling(jobId: string): void {
    const id = pollingIntervals.value.get(jobId)
    if (id !== undefined) {
      clearInterval(id)
      pollingIntervals.value.delete(jobId)
    }
  }

  /** Resume polling for any in-flight jobs on store hydration. */
  function resumePollingForActiveJobs(): void {
    jobs.value
      .filter(j => ["pending", "transcribing", "matching"].includes(j.status))
      .forEach(j => startPolling(j.job_id))
  }

  return {
    speakers, speakerNextCursor,
    jobs, jobNextCursor,
    activeJobId, activeJob, activeTranscript,
    readySpeakers,
    loadSpeakers, createSpeaker, deleteSpeaker, uploadSample, deleteSample,
    loadJobs, submitJob, selectJob, loadTranscript, deleteJob,
    resumePollingForActiveJobs,
  }
})
```

---

## Views

### `src/views/TranscribeView.vue`

Top-level layout for the transcription feature. Two-panel split matching the general feel of `ChatView.vue`.

```
┌──────────────────────────────────────────────────────────────┐
│  ConversationSidebar (with Chat / Transcribe nav at top)     │
├──────────────────────┬───────────────────────────────────────┤
│  SpeakerPanel        │  JobPanel                             │
│  ─────────────────   │  ───────────────────────────────────  │
│  + New Speaker       │  + New Job (form, collapsed)          │
│                      │                                       │
│  Alice               │  Job #1  [complete]  ← selected      │
│    sample_1 ✓ ready  │  Job #2  [transcribing]  ⟳           │
│    + Add sample      │  Job #3  [failed]                     │
│                      │                                       │
│  Bob (no samples)    │  ── Transcript ──────────────────     │
│    + Add sample      │  [00:00:00] Alice: Good morning…      │
│                      │  [00:00:05] Bob: Thanks Alice…        │
└──────────────────────┴───────────────────────────────────────┘
```

```vue
<!-- src/views/TranscribeView.vue -->
<script setup lang="ts">
import { onMounted } from "vue"
import ConversationSidebar from "@/components/ConversationSidebar.vue"
import SpeakerPanel from "@/components/transcribe/SpeakerPanel.vue"
import JobPanel from "@/components/transcribe/JobPanel.vue"
import { useTranscribeStore } from "@/stores/transcribe"

const store = useTranscribeStore()

onMounted(async () => {
  await Promise.all([store.loadSpeakers(true), store.loadJobs(true)])
  store.resumePollingForActiveJobs()
})
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-gray-50">
    <ConversationSidebar />
    <div class="flex flex-1 overflow-hidden">
      <SpeakerPanel class="w-72 flex-shrink-0 border-r border-gray-200 overflow-y-auto" />
      <JobPanel class="flex-1 overflow-y-auto" />
    </div>
  </div>
</template>
```

---

## Components

All transcription components live under `src/components/transcribe/`.

### `SpeakerPanel.vue`

Displays the speaker list with a "New Speaker" form at the top.

**State (local):**
- `newSpeakerName: string` — controlled input
- `isCreating: boolean` — disables button during API call
- `expandedSpeakerId: string | null` — accordion state

**Template structure:**

```
SpeakerPanel
├── New speaker input + Create button
│     validation: name.trim().length > 0
│     on submit: store.createSpeaker(name), clear input
│
└── For each speaker in store.speakers:
      SpeakerProfileCard
```

### `SpeakerProfileCard.vue`

Props: `speaker: SpeakerProfile`

Expandable card showing speaker name, sample list, and upload control.

```
┌── [▶] Alice ─────────────────── [Delete]  ──────────────────┐
│   (collapsed by default)                                     │
└──────────────────────────────────────────────────────────────┘

┌── [▼] Alice ─────────────────── [Delete]  ──────────────────┐
│   ● sample_1  3/3/2026  14.2s  [ready ✓]        [Remove]   │
│   ● sample_2  3/3/2026  11.0s  [processing ⟳]   [Remove]   │
│                                                              │
│   ┌──────────────────────────────────────────┐              │
│   │  Drop audio file or click to browse      │              │
│   │  (10 – 60 s, any audio format)           │              │
│   └──────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

**Behaviour:**
- Delete speaker: confirm dialog (`window.confirm`) → `store.deleteSpeaker(id)`
- Remove sample: `store.deleteSample(speakerId, sampleId)`
- Upload area: drag-and-drop or click; calls `store.uploadSample(speakerId, file)`; shows inline spinner during upload; shows API error message inline on `duration_too_short`, `duration_too_long`, `unsupported_format`

### `AudioFileDropzone.vue`

Reusable component used in both `SpeakerProfileCard` and `NewJobForm`.

Props:
```typescript
interface Props {
  accept?: string       // default: "audio/*"
  maxSizeMb?: number    // default: 2048
  label?: string
}
emit("file-selected", file: File)
```

Template: a `<div>` with `@dragover.prevent`, `@drop.prevent`, `@click` → triggers hidden `<input type="file">`. Shows filename + size after selection. Error if file exceeds `maxSizeMb`.

### `SpeakerSampleRow.vue`

Props: `sample: SpeakerSample`, `speakerName: string`

Displays one row in the sample list: date, duration, `SampleStatusBadge`, delete button.

### `SampleStatusBadge.vue`

Props: `status: 'processing' | 'ready' | 'failed'`

Renders a small pill:
- `processing`: yellow, rotating spinner icon
- `ready`: green, checkmark
- `failed`: red, ✕

### `JobPanel.vue`

Right panel with new-job form (collapsible) and job list. When a job is selected, the transcript is shown below the list.

**State (local):**
- `showNewJobForm: boolean`

**Template:**

```
JobPanel
├── [+ New Job] button → toggles NewJobForm
├── NewJobForm (v-if="showNewJobForm")
├── Job list
│     For each job in store.jobs:
│       TranscribeJobCard (clickable, highlights active)
└── TranscriptDisplay (v-if="store.activeTranscript")
```

### `NewJobForm.vue`

Emits `submitted` when upload flow completes (parent collapses the form).

**Local state:**
- `audioFile: File | null`
- `speakerCountHint: number = 2`
- `selectedSpeakerIds: string[] = []`
- `language: string = 'en-US'`
- `uploading: boolean`
- `uploadError: string | null`
- `uploadProgress: number` — 0–100, updated via XHR or fetch streaming if possible; or just a spinner

**Fields:**
1. `AudioFileDropzone` — required
2. `<select>` for language (pre-populate with common BCP-47 codes: en-US, en-GB, fr-FR, de-DE, es-ES, ja-JP)
3. Number input: Speaker count hint (2–30)
4. Multi-select checklist of `store.speakers` — shows each speaker name; selecting restricts matching
5. Submit button (disabled until `audioFile` is set and not uploading)

**On submit:**
```
uploading = true
try {
  const jobId = await store.submitJob(audioFile, { speakerCountHint, selectedSpeakerIds, language })
  store.selectJob(jobId)
  emit("submitted")
} catch (e) {
  uploadError = e.message
} finally {
  uploading = false
}
```

Show `uploadError` as inline red text below the button. Distinguish 429 ("Maximum concurrent jobs reached") from generic errors.

### `TranscribeJobCard.vue`

Props: `job: TranscriptionJob`, `isActive: boolean`

Compact card in the job list:

```
┌──────────────────────────────────────────────────────┐
│  Mar 3, 2026  14:02          [complete ✓]  [Delete]  │
│  en-US · 3 speakers                                   │
└──────────────────────────────────────────────────────┘
```

- Click card body: `store.selectJob(job.job_id)`
- Click Delete: confirm → `store.deleteJob(job.job_id)`
- Highlighted border when `isActive`
- For `failed` jobs: show `error_message` as small red text; if `partial_transcript_available`, show "Partial transcript available" note

### `JobStatusBadge.vue`

Props: `status: TranscriptionJob['status']`

| Status | Colour | Icon |
|---|---|---|
| `pending` | gray | clock |
| `transcribing` | blue | spinning |
| `matching` | purple | spinning |
| `complete` | green | ✓ |
| `failed` | red | ✕ |

### `TranscriptDisplay.vue`

Props: `transcript: TranscriptResponse`

Renders the segment list and an optional download link.

```
[Download transcript.txt]   ← only when transcript_url is set

[00:00:00]  Alice    Good morning everyone, let's get started.
[00:00:05]  Bob      Thanks Alice, I have the Q3 numbers ready.
[00:00:11]  Alice    Great, please go ahead.
[00:00:14]  spk_2    The figures show a 12% increase.
              ↑ italic, lighter colour for anonymous labels
```

**Template for each segment:**

```vue
<div class="flex gap-3 py-1 text-sm">
  <span class="text-gray-400 font-mono w-20 flex-shrink-0">
    {{ formatTime(segment.start_time) }}
  </span>
  <span
    class="w-24 flex-shrink-0 font-medium truncate"
    :class="segment.speaker_name ? 'text-gray-800' : 'text-gray-400 italic'"
  >
    {{ segment.speaker_name ?? segment.anonymous_label }}
  </span>
  <span class="text-gray-700">{{ segment.text }}</span>
</div>
```

`formatTime(seconds: number): string` — formats as `HH:MM:SS`, e.g. `"00:01:34"`.

The download link (`transcript_url`) opens in a new tab — it's a pre-signed S3 GET URL valid for 60 minutes.

---

## Error Handling

All API errors from `transcribeApi.ts` propagate as axios `AxiosError`. Components catch these and display inline messages. Key cases:

| HTTP Status | API error_code | User message |
|---|---|---|
| 422 `duration_too_short` | | "Audio must be at least 10 seconds long." |
| 422 `duration_too_long` | | "Audio must be 60 seconds or shorter." |
| 422 `unsupported_format` | | "Unsupported audio format. Try MP3, WAV, or M4A." |
| 429 | | "You have 3 active jobs. Wait for one to finish." |
| 409 | | "Transcript not yet available." |
| 404 | | "Not found." |

Extract `error_code` from `error.response?.data?.detail` or `error.response?.data?.error_code`.

---

## Loading and Empty States

- **Speaker panel loading:** skeleton rows (3× gray rounded bars) during initial `loadSpeakers`
- **No speakers:** "No speakers yet. Add a speaker profile to enable named transcripts." with a call-to-action button
- **Job panel loading:** skeleton cards
- **No jobs:** "No transcription jobs yet. Upload an audio file to get started."
- **Job in progress:** `TranscriptDisplay` replaced by a status message: "Transcription in progress — checking every 5 seconds…"

---

## File Summary

| File | Action |
|---|---|
| `src/types/index.ts` | Append new interfaces |
| `src/lib/transcribeApi.ts` | New |
| `src/stores/transcribe.ts` | New |
| `src/router/index.ts` | Add `/transcribe` route |
| `src/views/TranscribeView.vue` | New |
| `src/components/ConversationSidebar.vue` | Add nav tabs |
| `src/components/transcribe/SpeakerPanel.vue` | New |
| `src/components/transcribe/SpeakerProfileCard.vue` | New |
| `src/components/transcribe/AudioFileDropzone.vue` | New |
| `src/components/transcribe/SpeakerSampleRow.vue` | New |
| `src/components/transcribe/SampleStatusBadge.vue` | New |
| `src/components/transcribe/JobPanel.vue` | New |
| `src/components/transcribe/NewJobForm.vue` | New |
| `src/components/transcribe/TranscribeJobCard.vue` | New |
| `src/components/transcribe/JobStatusBadge.vue` | New |
| `src/components/transcribe/TranscriptDisplay.vue` | New |

---

## Implementation Order

1. Types (`types/index.ts`)
2. `transcribeApi.ts`
3. `transcribe.ts` store
4. Router entry
5. `TranscribeView.vue` (bare scaffold with panels)
6. `AudioFileDropzone.vue` (reusable; unblock both panels)
7. Speaker panel components (`SpeakerPanel`, `SpeakerProfileCard`, `SpeakerSampleRow`, `SampleStatusBadge`)
8. Job panel components (`NewJobForm`, `TranscribeJobCard`, `JobStatusBadge`)
9. `TranscriptDisplay.vue`
10. `JobPanel.vue` (assembles job components)
11. Nav tabs in `ConversationSidebar.vue`
12. Wire polling resume in `TranscribeView.vue`
13. Loading/empty states and error handling passes

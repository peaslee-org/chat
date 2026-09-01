import { defineStore } from "pinia"
import { ref, reactive, computed } from "vue"
import axios from "axios"
import * as api from "@/lib/transcribeApi"
import type { SpeakerProfile, TranscriptionJob, TranscriptResponse, JobLogEntry, TurnDistanceData } from "@/types"

export interface Toast {
  id: number
  message: string
  speakerId?: string
  sampleId?: string
}

let nextToastId = 0

export const useTranscribeStore = defineStore("transcribe", () => {

  // ── State ─────────────────────────────────────────────────────────────

  const speakers = ref<SpeakerProfile[]>([])
  const speakerNextCursor = ref<string | null>(null)

  const jobs = ref<TranscriptionJob[]>([])
  const jobNextCursor = ref<string | null>(null)

  const activeJobId = ref<string | null>(null)
  const activeTranscript = ref<TranscriptResponse | null>(null)

  // job_id → activity log entries
  const jobLogs = ref<Record<string, JobLogEntry[]>>({})

  // job_id → turn distance data (lazy-loaded on demand)
  const turnDistanceData = ref<Record<string, TurnDistanceData[]>>({})

  function logJob(jobId: string, entry: JobLogEntry) {
    if (!jobLogs.value[jobId]) jobLogs.value[jobId] = []
    jobLogs.value[jobId].push(entry)
  }

  function ts() { return new Date().toISOString() }

  const POLL_INTERVAL_NORMAL = Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 10_000
  const POLL_INTERVAL_PAUSED = Number(import.meta.env.VITE_POLL_INTERVAL_PAUSED_MS) || 60_000

  // job_id → timeout ID (for polling cleanup)
  const pollingIntervals = ref<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  // job IDs with an in-flight status request
  const pollingActive = reactive(new Set<string>())

  // jobs waiting to confirm once their speaker samples finish processing
  // job_id → speakerIds[]
  const pendingConfirms = ref<Map<string, string[]>>(new Map())

  // speaker_id → interval ID (for sample status polling)
  const samplePollingIntervals = ref<Map<string, ReturnType<typeof setInterval>>>(new Map())

  // ── Toasts ────────────────────────────────────────────────────────────
  const toasts = ref<Toast[]>([])

  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function pushToast(message: string, meta?: { speakerId?: string; sampleId?: string }): void {
    const id = nextToastId++
    toasts.value.push({ id, message, ...meta })
    setTimeout(() => dismissToast(id), 8000)
  }

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

  async function createSpeaker(name?: string): Promise<string> {
    const profile = await api.createSpeaker(name)
    speakers.value.unshift({ ...profile, samples: [] })
    return String(profile.speaker_id)
  }

  async function renameSpeaker(speakerId: string, name: string): Promise<void> {
    await api.renameSpeaker(speakerId, name)
    const speaker = speakers.value.find(s => s.speaker_id === speakerId)
    if (speaker) speaker.speaker_name = name
  }

  async function deleteSpeaker(speakerId: string): Promise<void> {
    await api.deleteSpeaker(speakerId)
    speakers.value = speakers.value.filter(s => s.speaker_id !== speakerId)
  }

  async function uploadSample(speakerId: string, file: File): Promise<void> {
    // 1. Initiate
    const { sample_id, upload_url } = await api.initSampleUpload(speakerId)
    // 2. Upload to S3 (no auth header)
    await api.uploadToS3(upload_url, file)
    // 3. Confirm — response reflects actual initial status (ready in dev, processing in prod)
    const confirmed = await api.confirmSampleUpload(speakerId, sample_id)
    // 4. Add sample using confirmed status and duration from the API
    const speaker = speakers.value.find(s => s.speaker_id === speakerId)
    if (speaker) {
      speaker.samples.push(confirmed)
      if (confirmed.status === "processing") startSamplePolling(speakerId)
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

  async function submitSampleJob(): Promise<string> {
    const t0 = ts()
    const { job_id, speaker_ids } = await api.createSampleJob()
    logJob(job_id, { ts: t0, direction: 'request', label: 'POST /jobs/sample' })
    logJob(job_id, { ts: ts(), direction: 'response', label: '202 transcribing', detail: job_id })
    const now = ts()
    jobs.value.unshift({
      job_id,
      status: "transcribing",
      speaker_count_hint: 2,
      language: "en-US",
      speaker_ids,
      error_message: null,
      partial_transcript_available: false,
      matched_speaker_count: null,
      total_segment_count: null,
      created_at: now,
      updated_at: now,
      completed_at: null,
    })
    startPolling(job_id)
    return job_id
  }

  async function submitJob(
    file: File,
    params: { speakerCountHint: number; speakerIds: string[]; language: string },
  ): Promise<string> {
    // 1. Create job record
    const t0 = ts()
    let job_id: string, upload_url: string
    try {
      ;({ job_id, upload_url } = await api.createJob({
        speaker_count_hint: params.speakerCountHint,
        speaker_ids: params.speakerIds.length ? params.speakerIds : undefined,
        language: params.language,
      }))
      logJob(job_id, { ts: t0, direction: 'request', label: 'POST /jobs' })
      logJob(job_id, { ts: ts(), direction: 'response', label: '201 Created', detail: job_id })
    } catch (err) {
      throw err
    }
    // 2. Add to local job list as pending while uploading
    const now = ts()
    jobs.value.unshift({
      job_id,
      status: "pending",
      speaker_count_hint: params.speakerCountHint,
      language: params.language,
      speaker_ids: params.speakerIds,
      error_message: null,
      partial_transcript_available: false,
      matched_speaker_count: null,
      total_segment_count: null,
      created_at: now,
      updated_at: now,
      completed_at: null,
    })
    // 3. Upload to S3
    const t1 = ts()
    logJob(job_id, { ts: t1, direction: 'request', label: `PUT S3 (${(file.size / 1024).toFixed(0)} KB)` })
    try {
      await api.uploadToS3(upload_url, file)
      logJob(job_id, { ts: ts(), direction: 'response', label: '200 S3 OK' })
    } catch (err) {
      logJob(job_id, { ts: ts(), direction: 'response', label: 'S3 upload failed', error: true })
      throw err
    }
    // 4. Confirm — transitions job to transcribing; on 409 (samples still processing)
    //    park the job and let sample polling trigger the confirm once samples are ready.
    logJob(job_id, { ts: ts(), direction: 'request', label: `POST /jobs/${job_id.slice(0, 8)}…/confirm` })
    try {
      await api.confirmJobUpload(job_id)
      logJob(job_id, { ts: ts(), direction: 'response', label: '200 transcribing' })
      const idx = jobs.value.findIndex(j => j.job_id === job_id)
      if (idx !== -1) jobs.value[idx] = { ...jobs.value[idx], status: "transcribing" }
      startPolling(job_id)
    } catch (err: any) {
      if (err?.response?.status === 409) {
        logJob(job_id, { ts: ts(), direction: 'response', label: '409 — samples still processing, will confirm when ready' })
        pendingConfirms.value.set(job_id, params.speakerIds)
      } else {
        logJob(job_id, { ts: ts(), direction: 'response', label: 'confirm failed', error: true })
        throw err
      }
    }
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
    logJob(jobId, { ts: ts(), direction: 'request', label: `GET /jobs/${jobId.slice(0, 8)}…/transcript` })
    try {
      const result = await api.getTranscript(jobId)
      logJob(jobId, { ts: ts(), direction: 'response', label: `200 OK`, detail: `${result.segments.length} segments` })
      activeTranscript.value = result
    } catch (err) {
      logJob(jobId, { ts: ts(), direction: 'response', label: 'transcript fetch failed', error: true })
      throw err
    }
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

    async function tick() {
      pollingActive.add(jobId)
      logJob(jobId, { ts: ts(), direction: 'request', label: `GET /jobs/${jobId.slice(0, 8)}… (poll)` })
      let updated: TranscriptionJob | null = null
      try {
        updated = await api.getJobStatus(jobId)
        logJob(jobId, { ts: ts(), direction: 'response', label: `200 ${updated.status}` })
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          logJob(jobId, { ts: ts(), direction: 'response', label: '404 — job not found, removing', error: true })
          pollingActive.delete(jobId)
          stopPolling(jobId)
          jobs.value = jobs.value.filter(j => j.job_id !== jobId)
          if (activeJobId.value === jobId) activeJobId.value = null
          return
        }
        logJob(jobId, { ts: ts(), direction: 'response', label: 'poll failed', error: true })
      } finally {
        pollingActive.delete(jobId)
      }
      if (!updated) {
        if (pollingIntervals.value.has(jobId)) {
          pollingIntervals.value.set(jobId, setTimeout(tick, POLL_INTERVAL_NORMAL))
        }
        return
      }
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
        return
      }
      if (pollingIntervals.value.has(jobId)) {
        const interval = updated.worker_state === "off" ? POLL_INTERVAL_PAUSED : POLL_INTERVAL_NORMAL
        pollingIntervals.value.set(jobId, setTimeout(tick, interval))
      }
    }

    pollingIntervals.value.set(jobId, setTimeout(tick, POLL_INTERVAL_NORMAL))
  }

  function stopPolling(jobId: string): void {
    const id = pollingIntervals.value.get(jobId)
    if (id !== undefined) {
      clearTimeout(id)
      pollingIntervals.value.delete(jobId)
    }
  }

  /** Resume polling for any in-flight jobs on store hydration. */
  function resumePollingForActiveJobs(): void {
    jobs.value
      .filter(j => ["pending", "transcribing", "matching"].includes(j.status))
      .forEach(j => startPolling(j.job_id))
  }

  // ── Sample polling ────────────────────────────────────────────────────

  // 200 polls × 3 s = 10 minutes max before giving up on a stuck sample
  const MAX_SAMPLE_POLLS = 200
  const samplePollCounts = new Map<string, number>()

  function startSamplePolling(speakerId: string): void {
    if (samplePollingIntervals.value.has(speakerId)) return
    samplePollCounts.set(speakerId, 0)
    const id = setInterval(async () => {
      const count = (samplePollCounts.get(speakerId) ?? 0) + 1
      samplePollCounts.set(speakerId, count)
      if (count >= MAX_SAMPLE_POLLS) {
        stopSamplePolling(speakerId)
        return
      }
      const previous = speakers.value.find(s => s.speaker_id === speakerId)
      const updated = await api.getSpeaker(speakerId)
      const idx = speakers.value.findIndex(s => s.speaker_id === speakerId)
      if (idx !== -1) speakers.value[idx] = updated
      // Detect processing → failed transitions and show a toast
      if (previous) {
        for (const sample of updated.samples) {
          const prev = previous.samples.find(s => s.sample_id === sample.sample_id)
          if (prev?.status === "processing" && sample.status === "failed") {
            const name = updated.speaker_name ?? "Unnamed speaker"
            const shortId = sample.sample_id.slice(0, 8)
            const detail = sample.error_message ? `: ${sample.error_message}` : ""
            pushToast(
              `Voice sample for "${name}" failed${detail} (ID: ${shortId}) — please re-upload.`,
              { speakerId, sampleId: sample.sample_id },
            )
          }
        }
      }
      const stillProcessing = updated.samples.some(sm => sm.status === "processing")
      if (!stillProcessing) stopSamplePolling(speakerId)
    }, 3000)
    samplePollingIntervals.value.set(speakerId, id)
  }

  function stopSamplePolling(speakerId: string): void {
    const id = samplePollingIntervals.value.get(speakerId)
    if (id !== undefined) {
      clearInterval(id)
      samplePollingIntervals.value.delete(speakerId)
      samplePollCounts.delete(speakerId)
    }
    tryPendingConfirms()
  }

  async function tryPendingConfirms(): Promise<void> {
    for (const [jobId, speakerIds] of pendingConfirms.value) {
      const allReady = speakerIds.every(sid => {
        const spk = speakers.value.find(s => s.speaker_id === sid)
        return spk?.samples.some(sm => sm.status === "ready")
      })
      if (!allReady) continue
      pendingConfirms.value.delete(jobId)
      logJob(jobId, { ts: ts(), direction: 'request', label: `POST /jobs/${jobId.slice(0, 8)}…/confirm (auto)` })
      try {
        await api.confirmJobUpload(jobId)
        logJob(jobId, { ts: ts(), direction: 'response', label: '200 transcribing' })
        const idx = jobs.value.findIndex(j => j.job_id === jobId)
        if (idx !== -1) jobs.value[idx] = { ...jobs.value[idx], status: "transcribing" }
        startPolling(jobId)
      } catch (err) {
        logJob(jobId, { ts: ts(), direction: 'response', label: 'auto-confirm failed', error: true })
      }
    }
  }

  async function loadTurnDistances(jobId: string): Promise<void> {
    if (turnDistanceData.value[jobId]) return
    const res = await api.fetchTurnDistances(jobId)
    turnDistanceData.value[jobId] = res.turns
  }

  /** Resume polling for any speakers with processing samples on store hydration.
   *  Skips samples already stuck past the 10-minute polling window. */
  function resumePollingForProcessingSamples(): void {
    const cutoff = Date.now() - MAX_SAMPLE_POLLS * 3000
    speakers.value
      .filter(s => s.samples.some(
        sm => sm.status === "processing" && new Date(sm.created_at).getTime() > cutoff
      ))
      .forEach(s => startSamplePolling(s.speaker_id))
  }

  async function setVisibility(jobId: string, isPublic: boolean) {
    const updated = await api.setJobVisibility(jobId, isPublic)
    const idx = jobs.value.findIndex((j) => j.job_id === updated.job_id)
    if (idx >= 0) jobs.value[idx] = { ...jobs.value[idx], ...updated }
  }

  return {
    speakers, speakerNextCursor,
    jobs, jobNextCursor,
    activeJobId, activeJob, activeTranscript,
    jobLogs,
    pollingActive,
    toasts,
    readySpeakers,
    turnDistanceData,
    loadSpeakers, createSpeaker, renameSpeaker, deleteSpeaker, uploadSample, deleteSample,
    loadJobs, submitJob, submitSampleJob, selectJob, loadTranscript, deleteJob,
    dismissToast, pushToast,
    loadTurnDistances,
    resumePollingForActiveJobs, resumePollingForProcessingSamples,
    setVisibility,
  }
})

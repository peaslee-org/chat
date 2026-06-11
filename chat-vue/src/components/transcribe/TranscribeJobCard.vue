<script setup lang="ts">
import type { TranscriptionJob } from "@/types"
import { useTranscribeStore } from "@/stores/transcribe"
import JobStatusBadge from "./JobStatusBadge.vue"

const props = defineProps<{
  job: TranscriptionJob
  isActive: boolean
}>()

const store = useTranscribeStore()

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatDuration(startStr: string, endStr: string): string {
  const ms = new Date(endStr).getTime() - new Date(startStr).getTime()
  const totalSeconds = Math.floor(ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${m}m ${s}s`
}

async function handleDelete(e: Event) {
  e.stopPropagation()
  if (!window.confirm("Delete this transcription job?")) return
  await store.deleteJob(props.job.job_id)
}
</script>

<template>
  <div
    class="border rounded-lg p-3 mb-2 cursor-pointer transition-colors hover:bg-gray-50"
    :class="isActive ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 bg-white'"
    @click="store.selectJob(job.job_id)"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs text-gray-500">{{ formatDate(job.created_at) }}</span>
      <div class="flex items-center gap-2">
        <JobStatusBadge
          :status="job.status"
          :logs="store.jobLogs[job.job_id]"
          :worker-paused="job.worker_paused"
          :is-polling="store.pollingActive.has(job.job_id)"
        />
        <button
          class="text-gray-400 hover:text-red-500 text-xs transition-colors"
          @click="handleDelete"
        >
          Delete
        </button>
      </div>
    </div>
    <p class="text-xs text-gray-500 mt-1">
      {{ job.language }} · {{ job.speaker_count_hint }} speakers
    </p>
    <p v-if="job.status === 'complete' && job.completed_at" class="text-xs text-gray-400 mt-1">
      Completed in {{ formatDuration(job.created_at, job.completed_at) }}
      <span v-if="job.total_segment_count != null">
        · {{ job.matched_speaker_count }}/{{ job.total_segment_count }} segments matched
      </span>
    </p>
    <p v-if="job.status === 'failed' && job.error_message" class="text-xs text-red-600 mt-1">
      {{ job.error_message }}
    </p>
    <p v-if="job.status === 'failed' && job.partial_transcript_available" class="text-xs text-amber-600 mt-1">
      Partial transcript available
    </p>
  </div>
</template>

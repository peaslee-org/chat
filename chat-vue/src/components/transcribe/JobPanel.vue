<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue"
import { useTranscribeStore } from "@/stores/transcribe"
import NewJobForm from "./NewJobForm.vue"
import TranscribeJobCard from "./TranscribeJobCard.vue"
import TranscriptDisplay from "./TranscriptDisplay.vue"

const store = useTranscribeStore()
const showNewJobForm = ref(false)

function onSubmitted() {
  showNewJobForm.value = false
}

// ── Elapsed time for in-progress jobs ─────────────────────────────────────

const now = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null

const activeJobInProgress = computed(() =>
  store.activeJob && ["pending", "transcribing", "matching"].includes(store.activeJob.status)
)

watch(activeJobInProgress, (inProgress) => {
  if (inProgress && !ticker) {
    ticker = setInterval(() => { now.value = Date.now() }, 1000)
  } else if (!inProgress && ticker) {
    clearInterval(ticker)
    ticker = null
  }
}, { immediate: true })

onUnmounted(() => {
  if (ticker) clearInterval(ticker)
})

const elapsedLabel = computed(() => {
  if (!store.activeJob) return ""
  const startMs = new Date(store.activeJob.created_at).getTime()
  const totalSeconds = Math.floor((now.value - startMs) / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${m}m ${s}s`
})

const workerPaused = computed(() => !!store.activeJob?.worker_paused)

const statusMessage = computed(() => {
  if (!store.activeJob) return ""
  if (workerPaused.value && ["transcribing", "matching"].includes(store.activeJob.status)) {
    return "Transcription service is paused. Your job is queued and will be processed automatically when the service resumes."
  }
  switch (store.activeJob.status) {
    case "pending":     return "Uploading audio…"
    case "transcribing": return "Transcribing audio — checking every 5 seconds…"
    case "matching":    return "Matching speakers — checking every 5 seconds…"
    default:            return ""
  }
})
</script>

<template>
  <div class="flex flex-col h-full bg-gray-50 p-4">
    <!-- Header -->
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-gray-700">Transcription Jobs</h2>
      <button
        class="text-sm px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-500 transition-colors"
        @click="showNewJobForm = !showNewJobForm"
      >
        {{ showNewJobForm ? '✕ Cancel' : '+ New Job' }}
      </button>
    </div>

    <!-- New job form -->
    <NewJobForm v-if="showNewJobForm" @submitted="onSubmitted" />

    <!-- Job list -->
    <div v-if="store.jobs.length === 0 && !showNewJobForm" class="text-center py-8 text-sm text-gray-500">
      <p>No transcription jobs yet.</p>
      <p class="text-xs text-gray-400 mt-1">Upload an audio file to get started.</p>
    </div>

    <div v-else class="flex-1 overflow-y-auto">
      <TranscribeJobCard
        v-for="job in store.jobs"
        :key="job.job_id"
        :job="job"
        :is-active="job.job_id === store.activeJobId"
      />
    </div>

    <!-- Transcript area -->
    <div v-if="store.activeJobId" class="mt-4 border-t border-gray-200 pt-4">
      <div
        v-if="activeJobInProgress"
        class="text-sm text-gray-500 text-center py-4 space-y-1"
      >
        <p>{{ statusMessage }}</p>
        <p class="text-xs text-gray-400">Elapsed: {{ elapsedLabel }}</p>
      </div>
      <TranscriptDisplay v-else-if="store.activeTranscript" :transcript="store.activeTranscript" />
    </div>
  </div>
</template>

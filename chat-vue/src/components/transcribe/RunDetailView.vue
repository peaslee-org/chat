<script setup lang="ts">
import { ref, computed, watch } from "vue"
import axios from "axios"
import { useTranscribeStore } from "@/stores/transcribe"
import { workerStateLabel } from "@/lib/workerState"
import {
  useMatchingThresholds,
  computeTurns,
  type ComputedTurn,
} from "@/composables/useMatchingThresholds"
import TranscriptDisplay from "./TranscriptDisplay.vue"
import SpeakerProfileCard from "./SpeakerProfileCard.vue"
import TranscribeJobCard from "./TranscribeJobCard.vue"
import NewJobForm from "./NewJobForm.vue"
import MatchingAnalysis from "./MatchingAnalysis.vue"
import PublicToggle from "@/components/PublicToggle.vue"

const props = defineProps<{
  showNewJobForm: boolean
}>()

const emit = defineEmits<{
  "close-new-job-form": []
}>()

const store = useTranscribeStore()
const { cosineDistThreshold, separationMin, qualityMin, confidenceMin } = useMatchingThresholds()
const isCreating = ref(false)
const newSpeakerId = ref<string | null>(null)
const speakersOpen = ref(false)

const activeJob = computed(() => store.activeJob)

// Eagerly load turn distances whenever a complete job is active
watch(
  [() => store.activeJobId, () => store.activeJob?.status],
  async ([jobId, status]) => {
    if (jobId && status === "complete") {
      await store.loadTurnDistances(jobId as string)
    }
  },
  { immediate: true },
)

// ── Input audio: fetched lazily once a terminal (complete/failed) job is open ──
const TERMINAL_JOB_STATUSES = new Set(["complete", "failed"])
const jobAudioUrl = ref<string | null>(null)
const jobAudioError = ref<string | null>(null)

/** 404 means the object has expired from the bucket — say so; anything else is a generic
 *  fetch failure (network, 5xx, …). */
function audioErrorMessage(err: unknown): string {
  return axios.isAxiosError(err) && err.response?.status === 404
    ? "Input audio expired"
    : "Couldn't load input audio"
}

watch(
  [() => store.activeJobId, () => store.activeJob?.status],
  async ([jobId, status]) => {
    jobAudioUrl.value = null
    jobAudioError.value = null
    if (!jobId || !status || !TERMINAL_JOB_STATUSES.has(status)) return
    try {
      const urls = await store.fetchJobAudioUrl(jobId)
      if (store.activeJobId !== jobId) return
      jobAudioUrl.value = urls.url
    } catch (err) {
      if (store.activeJobId !== jobId) return
      jobAudioError.value = audioErrorMessage(err)
    }
  },
  { immediate: true },
)

/**
 * Re-resolve the download URL at click time (the store refreshes it within 30 s of expiry) so
 * a run detail left open past the 15-minute presign never hands S3 a stale link. Mirrors
 * ScanDetailView's mesh download() — the same server object, just re-presigned as an
 * attachment right before navigating.
 */
async function downloadJobAudio(): Promise<void> {
  const jobId = store.activeJobId
  if (!jobId) return
  try {
    const urls = await store.fetchJobAudioUrl(jobId)
    window.location.assign(urls.downloadUrl)
  } catch (err) {
    jobAudioUrl.value = null
    jobAudioError.value = audioErrorMessage(err)
  }
}

const computedTurnsForDisplay = computed((): ComputedTurn[] => {
  const jobId = store.activeJobId
  if (!jobId) return []
  const turns = store.turnDistanceData[jobId]
  if (!turns?.length) return []
  return computeTurns(turns, cosineDistThreshold.value, separationMin.value, qualityMin.value, confidenceMin.value)
})

const submittedSpeakers = computed(() => {
  if (!activeJob.value) return store.speakers
  const ids = new Set(activeJob.value.speaker_ids)
  if (ids.size === 0) return []
  return store.speakers.filter(s => ids.has(s.speaker_id))
})

function nextSpeakerName(): string {
  const existing = new Set(store.speakers.map(s => s.speaker_name))
  let n = 1
  while (existing.has(`Speaker ${n}`)) n++
  return `Speaker ${n}`
}

async function handleAddSpeaker() {
  if (isCreating.value) return
  isCreating.value = true
  try {
    const id = await store.createSpeaker(nextSpeakerName())
    newSpeakerId.value = id
  } finally {
    isCreating.value = false
  }
}

function onCardExpanded(speakerId: string) {
  if (newSpeakerId.value === speakerId) newSpeakerId.value = null
}

function onJobSubmitted() {
  emit("close-new-job-form")
}

const visibilityBusy = ref(false)
async function setVisibility(next: boolean) {
  if (!activeJob.value) return
  visibilityBusy.value = true
  try {
    await store.setVisibility(activeJob.value.job_id, next)
  } catch {
    store.pushToast("Couldn't update visibility — try again")
  } finally {
    visibilityBusy.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-full overflow-hidden bg-gray-50">
    <!-- New run form -->
    <template v-if="showNewJobForm">
      <div class="flex-1 overflow-y-auto p-6">
        <NewJobForm @submitted="onJobSubmitted" />
      </div>
    </template>

    <!-- Empty state (no form, no job selected) -->
    <template v-else-if="!store.activeJobId">
      <div class="flex-1 flex items-center justify-center text-gray-400">
        <p class="text-sm">Select a run or create a new one</p>
      </div>
    </template>

    <!-- Active job view -->
    <template v-else>
      <!-- Job header -->
      <div class="flex-shrink-0 px-4 pt-4">
        <div class="mb-2 flex justify-end">
          <PublicToggle
            v-if="activeJob"
            :is-public="activeJob.is_public ?? false"
            :busy="visibilityBusy"
            @toggle="(next) => setVisibility(next)"
          />
        </div>
        <TranscribeJobCard
          v-if="activeJob"
          :job="activeJob"
          :is-active="true"
        />

        <div
          v-if="activeJob && (activeJob.status === 'complete' || activeJob.status === 'failed')"
          class="mt-2 flex items-center gap-2 text-xs"
        >
          <span class="text-gray-500 shrink-0">Input audio</span>
          <template v-if="jobAudioUrl">
            <audio controls :src="jobAudioUrl" class="h-8 flex-1 min-w-0" />
            <a
              href="#"
              class="text-indigo-600 hover:text-indigo-500 shrink-0"
              @click.prevent="downloadJobAudio"
            >Download</a>
          </template>
          <span v-else-if="jobAudioError" class="text-gray-400">{{ jobAudioError }}</span>
        </div>
      </div>

      <!-- Transcript -->
      <div class="flex-1 overflow-y-auto px-4 pb-4 min-h-0">
        <div
          v-if="activeJob && ['pending', 'transcribing', 'matching'].includes(activeJob.status)"
          class="text-sm text-gray-500 text-center py-8"
        >
          <template v-if="activeJob.worker_state && activeJob.worker_state !== 'running' && ['transcribing', 'matching'].includes(activeJob.status)">
            {{ workerStateLabel(activeJob.worker_state, activeJob.estimated_wait_seconds) }}<span v-if="activeJob.gpu_notice"> — {{ activeJob.gpu_notice }}</span>
          </template>
          <template v-else>
            Transcription in progress — checking every 5 seconds…
          </template>
        </div>
        <TranscriptDisplay
          v-else-if="store.activeTranscript"
          :transcript="store.activeTranscript"
          :computed-turns="computedTurnsForDisplay"
        />
        <div v-else class="text-sm text-gray-400 text-center py-8">
          No transcript available.
        </div>
      </div>

      <!-- Matching Analysis -->
      <MatchingAnalysis
        v-if="activeJob && activeJob.status === 'complete'"
        :job-id="activeJob.job_id"
      />

      <!-- Speaker management -->
      <div class="flex-shrink-0 border-t border-gray-200 bg-white">
        <button
          class="w-full px-4 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors"
          @click="speakersOpen = !speakersOpen"
        >
          <h3 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Speakers</h3>
          <span class="text-gray-400 text-xs">{{ speakersOpen ? "▲" : "▼" }}</span>
        </button>

        <div v-if="speakersOpen" class="px-4 pb-4">
          <div
            v-if="submittedSpeakers.length === 0"
            class="text-xs text-gray-400 text-center py-2"
          >
            No speakers yet. Add a profile to enable named transcripts.
          </div>
          <div v-else class="max-h-64 overflow-y-auto mb-3">
            <SpeakerProfileCard
              v-for="speaker in submittedSpeakers"
              :key="speaker.speaker_id"
              :speaker="speaker"
              :auto-expand="speaker.speaker_id === newSpeakerId"
              @expanded="onCardExpanded(speaker.speaker_id)"
            />
          </div>
          <button
            :disabled="isCreating"
            class="w-full text-xs px-2.5 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleAddSpeaker"
          >
            + Add Speaker
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

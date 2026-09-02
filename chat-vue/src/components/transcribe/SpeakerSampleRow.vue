<script setup lang="ts">
import { ref } from "vue"
import type { SpeakerSample } from "@/types"
import { useTranscribeStore } from "@/stores/transcribe"
import SampleStatusBadge from "./SampleStatusBadge.vue"

const props = defineProps<{
  sample: SpeakerSample
  speakerId: string
  speakerName: string
}>()

const emit = defineEmits<{
  delete: []
}>()

const store = useTranscribeStore()
const playerOpen = ref(false)
const audioUrl = ref<string | null>(null)
const loading = ref(false)
const loadError = ref(false)

async function togglePlay() {
  if (playerOpen.value) {
    playerOpen.value = false
    return
  }
  playerOpen.value = true
  if (audioUrl.value) return
  loading.value = true
  loadError.value = false
  try {
    const urls = await store.fetchSampleAudioUrl(props.speakerId, props.sample.sample_id)
    audioUrl.value = urls.url
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

/**
 * Re-resolve the download URL at click time (the store refreshes it within 30 s of expiry) so
 * a panel left open past the 15-minute presign never hands S3 a stale link.
 */
async function downloadSample(): Promise<void> {
  try {
    const urls = await store.fetchSampleAudioUrl(props.speakerId, props.sample.sample_id)
    window.location.assign(urls.downloadUrl)
  } catch {
    audioUrl.value = null
    loadError.value = true
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString([], { month: 'numeric', day: 'numeric', year: 'numeric' })
}
</script>

<template>
  <div class="py-1 text-xs text-gray-600">
    <div class="flex items-center gap-2">
      <span class="text-gray-400">●</span>
      <span class="text-gray-500">{{ formatDate(sample.created_at) }}</span>
      <span v-if="sample.duration_seconds !== null" class="text-gray-500">
        {{ sample.duration_seconds.toFixed(1) }}s
      </span>
      <SampleStatusBadge :status="sample.status" />
      <button
        v-if="sample.status === 'ready'"
        type="button"
        data-testid="play-sample"
        :aria-label="playerOpen ? 'Hide sample audio' : 'Play sample audio'"
        class="text-gray-400 hover:text-indigo-500 transition-colors"
        @click="togglePlay"
      >
        {{ playerOpen ? 'Hide' : 'Play' }}
      </button>
      <button
        class="ml-auto text-gray-400 hover:text-red-500 transition-colors"
        @click="emit('delete')"
      >
        Remove
      </button>
    </div>
    <div v-if="playerOpen" class="mt-1 pl-4 flex items-center gap-2">
      <template v-if="audioUrl">
        <audio controls :src="audioUrl" class="h-8" />
        <a href="#" class="text-indigo-600 hover:text-indigo-500" @click.prevent="downloadSample">Download</a>
      </template>
      <span v-else-if="loading" class="text-gray-400">Loading…</span>
      <span v-else-if="loadError" class="text-gray-400">Couldn't load audio</span>
    </div>
    <p v-if="sample.status === 'failed' && sample.error_message" class="mt-0.5 pl-4 text-red-500 break-words">
      {{ sample.error_message }}
    </p>
    <p v-else-if="sample.status === 'failed'" class="mt-0.5 pl-4 text-red-500">
      Embedding failed — please re-upload. (ID: {{ sample.sample_id.slice(0, 8) }})
    </p>
  </div>
</template>

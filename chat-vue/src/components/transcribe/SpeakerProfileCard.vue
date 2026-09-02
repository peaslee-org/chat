<script setup lang="ts">
import { ref, onMounted } from "vue"
import axios from "axios"
import type { SpeakerProfile } from "@/types"
import { useTranscribeStore } from "@/stores/transcribe"
import AudioFileDropzone from "./AudioFileDropzone.vue"
import SpeakerSampleRow from "./SpeakerSampleRow.vue"

const props = defineProps<{
  speaker: SpeakerProfile
  autoExpand?: boolean
}>()

const emit = defineEmits<{
  expanded: []
}>()

const store = useTranscribeStore()
const isExpanded = ref(false)
const isUploading = ref(false)
const uploadError = ref<string | null>(null)
const isRenaming = ref(false)
const renameValue = ref("")

onMounted(() => {
  if (props.autoExpand) {
    isExpanded.value = true
    emit("expanded")
  }
})

function startRename() {
  renameValue.value = props.speaker.speaker_name ?? ""
  isRenaming.value = true
}

async function commitRename() {
  const name = renameValue.value.trim()
  isRenaming.value = false
  if (!name || name === props.speaker.speaker_name) return
  await store.renameSpeaker(props.speaker.speaker_id, name)
}

function cancelRename() {
  isRenaming.value = false
}

async function handleFileSelected(file: File) {
  isUploading.value = true
  uploadError.value = null
  try {
    await store.uploadSample(props.speaker.speaker_id, file)
  } catch (e) {
    uploadError.value = parseUploadError(e, props.speaker.speaker_id)
  } finally {
    isUploading.value = false
  }
}

function parseUploadError(e: unknown, speakerId?: string): string {
  if (axios.isAxiosError(e)) {
    const code = e.response?.data?.error_code ?? e.response?.data?.detail
    if (code === "duration_too_short") return "Audio must be at least 10 seconds long."
    if (code === "duration_too_long") return "Audio must be 60 seconds or shorter."
    if (code === "unsupported_format") return "Unsupported audio format. Try MP3, WAV, or M4A."
  }
  const suffix = speakerId ? ` (Speaker ID: ${speakerId.slice(0, 8)})` : ""
  return `Upload failed. Please try again.${suffix}`
}

async function handleDelete() {
  if (!window.confirm(`Delete speaker "${props.speaker.speaker_name ?? 'Unnamed speaker'}"?`)) return
  await store.deleteSpeaker(props.speaker.speaker_id)
}

async function handleDeleteSample(sampleId: string) {
  await store.deleteSample(props.speaker.speaker_id, sampleId)
}
</script>

<template>
  <div class="border border-gray-200 rounded-lg overflow-hidden mb-2">
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 bg-white">
      <button
        class="text-gray-400 hover:text-gray-600 text-xs"
        @click="isExpanded = !isExpanded"
      >
        {{ isExpanded ? '▼' : '▶' }}
      </button>

      <!-- Inline rename input -->
      <input
        v-if="isRenaming"
        v-model="renameValue"
        type="text"
        class="flex-1 text-sm font-medium border-b border-indigo-400 focus:outline-none bg-transparent"
        autofocus
        @blur="commitRename"
        @keydown.enter="commitRename"
        @keydown.escape="cancelRename"
      />
      <span
        v-else
        class="flex-1 text-sm font-medium text-gray-800 truncate cursor-text hover:text-indigo-600"
        title="Click to rename"
        @click="startRename"
      >
        {{ speaker.speaker_name ?? 'Unnamed speaker' }}
      </span>

      <button
        class="text-gray-400 hover:text-red-500 text-xs transition-colors"
        @click="handleDelete"
      >
        Delete
      </button>
    </div>

    <!-- Expanded body -->
    <div v-if="isExpanded" class="px-3 pb-3 bg-gray-50 space-y-1">
      <SpeakerSampleRow
        v-for="sample in speaker.samples"
        :key="sample.sample_id"
        :sample="sample"
        :speaker-id="speaker.speaker_id"
        :speaker-name="speaker.speaker_name ?? 'Unnamed speaker'"
        @delete="handleDeleteSample(sample.sample_id)"
      />

      <div class="pt-2">
        <div v-if="isUploading" class="text-xs text-gray-500 flex items-center gap-2">
          <svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Uploading…
        </div>
        <AudioFileDropzone
          v-else
          label="Drop audio file or click to browse"
          @file-selected="handleFileSelected"
        />
        <p v-if="uploadError" class="mt-1 text-xs text-red-600">{{ uploadError }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from "vue"
import axios from "axios"
import { useTranscribeStore } from "@/stores/transcribe"
import AudioFileDropzone from "./AudioFileDropzone.vue"
import AudioPlayer from "./AudioPlayer.vue"


const emit = defineEmits<{
  submitted: []
}>()

const store = useTranscribeStore()

interface PendingSpeaker {
  localId: string
  name: string
  file: File | null
  fileDuration: number | null
  editing: boolean
  editName: string
  editFile: File | null
  uploadError: string | null
}

function getAudioDuration(file: File): Promise<number> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const audio = new Audio(url)
    audio.addEventListener("loadedmetadata", () => { URL.revokeObjectURL(url); resolve(audio.duration) }, { once: true })
    audio.addEventListener("error", () => { URL.revokeObjectURL(url); resolve(NaN) }, { once: true })
  })
}

function formatDuration(secs: number): string {
  if (!isFinite(secs)) return ""
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

function formatFileDate(ms: number): string {
  return new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function speakerFileSummary(speaker: PendingSpeaker): string {
  if (!speaker.file) return ""
  const parts: string[] = [speaker.file.name]
  if (speaker.fileDuration === null) parts.push("…")
  else if (isFinite(speaker.fileDuration)) parts.push(formatDuration(speaker.fileDuration))
  parts.push(formatSize(speaker.file.size))
  parts.push(formatFileDate(speaker.file.lastModified))
  return parts.join(" · ")
}

const audioFile = ref<File | null>(null)
const audioDropzone = ref<InstanceType<typeof AudioFileDropzone> | null>(null)
const loadingSample = ref(false)
const speakerCountHint = ref(1)
const language = ref("en-US")
const uploading = ref(false)
const uploadError = ref<string | null>(null)
const pendingSpeakers = ref<PendingSpeaker[]>([])
let nextLocalId = 0

// Draft state for the "Add speaker" block
const draftName = ref("")
const draftFile = ref<File | null>(null)
const draftIsDragOver = ref(false)
const draftFileInput = ref<HTMLInputElement | null>(null)
const draftContainer = ref<HTMLElement | null>(null)
// Collapsed after first speaker is added; re-opened by "Add another speaker"
const draftOpen = ref(true)

// Unsaved-draft warning modal
const showUnsavedWarning = ref(false)
// null = triggered by focus-away, "submit" = triggered by submit button
const pendingAction = ref<"submit" | null>(null)

// Dynamic placeholder: "Speaker 1", "Speaker 2", …
const draftPlaceholder = computed(() => `Speaker ${pendingSpeakers.value.length + 1}`)
// Draft is "dirty" if the user has typed a name or picked a file
const draftHasContent = computed(() => draftName.value.trim() !== "" || draftFile.value !== null)

watch(
  () => pendingSpeakers.value.length,
  (len) => {
    if (len > 0) speakerCountHint.value = len
  },
)

const LANGUAGES = [
  { code: "en-US", label: "English (US)" },
  { code: "en-GB", label: "English (UK)" },
  { code: "fr-FR", label: "French" },
  { code: "de-DE", label: "German" },
  { code: "es-ES", label: "Spanish" },
  { code: "ja-JP", label: "Japanese" },
]

function commitDraft() {
  if (!draftName.value.trim() && !draftFile.value) return
  const name = draftName.value.trim() || draftPlaceholder.value
  const localId = String(nextLocalId++)
  const file = draftFile.value
  pendingSpeakers.value.push({
    localId,
    name,
    file,
    fileDuration: null,
    editing: false,
    editName: "",
    editFile: null,
    uploadError: null,
  })
  if (file) {
    getAudioDuration(file).then(d => {
      const sp = pendingSpeakers.value.find(s => s.localId === localId)
      if (sp) sp.fileDuration = d
    })
  }
  draftName.value = ""
  draftFile.value = null
  draftOpen.value = false
}

function handleDraftFocusOut() {
  // Use a microtask delay so the newly-focused element is settled
  setTimeout(() => {
    if (!draftContainer.value) return
    if (!draftContainer.value.contains(document.activeElement) && draftHasContent.value) {
      pendingAction.value = null
      showUnsavedWarning.value = true
    }
  }, 0)
}

function confirmSaveDraft() {
  commitDraft()
  showUnsavedWarning.value = false
  const action = pendingAction.value
  pendingAction.value = null
  if (action === "submit") doSubmit()
}

function discardDraft() {
  draftName.value = ""
  draftFile.value = null
  showUnsavedWarning.value = false
  const action = pendingAction.value
  pendingAction.value = null
  if (action === "submit") doSubmit()
}

function cancelWarning() {
  showUnsavedWarning.value = false
  pendingAction.value = null
}

function removeSpeaker(localId: string) {
  pendingSpeakers.value = pendingSpeakers.value.filter(s => s.localId !== localId)
}

function startEdit(speaker: PendingSpeaker) {
  speaker.editName = speaker.name
  speaker.editFile = speaker.file
  speaker.editing = true
}

function cancelEdit(speaker: PendingSpeaker) {
  speaker.editing = false
}

function saveEdit(speaker: PendingSpeaker) {
  speaker.name = speaker.editName.trim()
  if (speaker.editFile) {
    speaker.file = speaker.editFile
    speaker.fileDuration = null
    getAudioDuration(speaker.editFile).then(d => { speaker.fileDuration = d })
  }
  speaker.editing = false
}

async function loadSample() {
  loadingSample.value = true
  uploadError.value = null
  try {
    const jobId = await store.submitSampleJob()
    await store.selectJob(jobId)
    emit("submitted")
  } catch (e) {
    uploadError.value = parseJobError(e, null)
  } finally {
    loadingSample.value = false
  }
}

async function doSubmit() {
  uploading.value = true
  uploadError.value = null
  for (const pending of pendingSpeakers.value) pending.uploadError = null
  let submittedJobId: string | null = null
  try {
    const speakerIds: string[] = []
    for (const pending of pendingSpeakers.value) {
      const speakerId = await store.createSpeaker(pending.name || undefined)
      speakerIds.push(speakerId)
      if (pending.file) {
        try {
          await store.uploadSample(speakerId, pending.file)
        } catch (e) {
          pending.uploadError = parseSampleError(e, speakerId)
          throw e
        }
      }
    }
    const jobId = await store.submitJob(audioFile.value!, {
      speakerCountHint: speakerCountHint.value,
      speakerIds,
      language: language.value,
    })
    submittedJobId = jobId
    await store.selectJob(jobId)
    emit("submitted")
  } catch (e) {
    const hasSpeakerError = pendingSpeakers.value.some(s => s.uploadError)
    if (!hasSpeakerError) uploadError.value = parseJobError(e, submittedJobId)
  } finally {
    uploading.value = false
  }
}

async function handleSubmit() {
  if (!audioFile.value || uploading.value) return
  if (draftHasContent.value) {
    pendingAction.value = "submit"
    showUnsavedWarning.value = true
    return
  }
  await doSubmit()
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function parseSampleError(e: unknown, speakerId?: string): string {
  if (axios.isAxiosError(e)) {
    const code = e.response?.data?.error_code ?? e.response?.data?.detail
    if (code === "duration_too_short") return "Sample must be at least 10 seconds long."
    if (code === "duration_too_long") return "Sample must be 60 seconds or shorter."
    if (code === "unsupported_format") return "Unsupported format. Try MP3, WAV, or M4A."
  }
  const suffix = speakerId ? ` (Speaker ID: ${speakerId.slice(0, 8)})` : ""
  return `Sample upload failed.${suffix}`
}

function parseJobError(e: unknown, jobId?: string | null): string {
  if (axios.isAxiosError(e)) {
    if (e.response?.status === 429) return "You have 3 active jobs. Wait for one to finish."
    const code = e.response?.data?.error_code ?? e.response?.data?.detail
    if (code === "duration_too_short") return "Audio must be at least 10 seconds long."
    if (code === "duration_too_long") return "Audio must be 60 seconds or shorter."
    if (code === "unsupported_format") return "Unsupported audio format. Try MP3, WAV, or M4A."
  }
  const suffix = jobId ? ` (Job ID: ${jobId.slice(0, 8)})` : ""
  return `Submission failed. Please try again.${suffix}`
}
</script>

<template>
  <div class="border border-gray-200 rounded-lg p-4 mb-4 bg-white">
    <h3 class="text-base font-semibold text-gray-700 mb-3">New Transcription Job</h3>

    <div class="space-y-3">
      <!-- Audio file -->
      <div>
        <div class="flex items-baseline justify-between mb-1">
          <label class="block text-sm font-medium text-gray-600">Audio file *</label>
          <button
            type="button"
            class="text-xs text-indigo-600 hover:text-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            :disabled="loadingSample"
            @click="loadSample"
          >
            {{ loadingSample ? 'Loading…' : 'Try sample data' }}
          </button>
        </div>
        <AudioFileDropzone
          ref="audioDropzone"
          label="Drop audio file or click to browse"
          @file-selected="audioFile = $event"
        />
      </div>

      <!-- Speakers subsection -->
      <div class="border border-gray-200 rounded-lg bg-gray-50 p-3">
        <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Speakers <span class="font-normal normal-case text-gray-400">(optional)</span></p>

        <!-- Added speaker rows -->
        <div v-if="pendingSpeakers.length > 0" class="space-y-1.5 mb-2">
          <div
            v-for="speaker in pendingSpeakers"
            :key="speaker.localId"
            class="border rounded-md bg-white"
            :class="speaker.uploadError ? 'border-red-300' : 'border-gray-200'"
          >
            <!-- View row -->
            <div
              v-if="!speaker.editing"
              class="px-2 py-1.5 cursor-pointer hover:bg-gray-50 transition-colors rounded-md"
              @click="startEdit(speaker)"
            >
              <p class="text-sm text-gray-700">{{ speaker.name || "Unnamed speaker" }}</p>
              <p v-if="speaker.file" class="text-xs text-gray-400 tabular-nums truncate mt-0.5">{{ speakerFileSummary(speaker) }}</p>
            </div>
            <p v-if="speaker.uploadError" class="px-2 pb-1.5 text-xs text-red-600">{{ speaker.uploadError }}</p>

            <!-- Edit row -->
            <div v-if="speaker.editing" class="p-2">
              <div class="flex gap-2 items-stretch">
                <div class="flex-1 flex flex-col gap-1.5">
                  <input
                    v-model="speaker.editName"
                    type="text"
                    placeholder="Speaker name (optional)"
                    class="w-full text-sm border border-gray-300 rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <div
                    class="flex-1 border-2 border-dashed rounded-lg p-2 text-center cursor-pointer transition-colors"
                    :class="speaker.editFile ? 'border-green-300 bg-green-50' : 'border-gray-300 hover:border-gray-400'"
                    @dragover.prevent
                    @drop.prevent="(e) => { const f = e.dataTransfer?.files[0]; if (f) speaker.editFile = f }"
                    @click="(e) => (e.currentTarget as HTMLElement).querySelector('input')?.click()"
                  >
                    <input
                      type="file"
                      accept="audio/*"
                      class="hidden"
                      @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) speaker.editFile = f }"
                    />
                    <div v-if="speaker.editFile" class="text-sm text-gray-700">
                      <span class="font-medium">{{ speaker.editFile.name }}</span>
                      <span class="text-gray-400 ml-2">({{ formatSize(speaker.editFile.size) }})</span>
                      <div class="mt-2 pt-2 border-t border-green-200" @click.stop>
                        <AudioPlayer :file="speaker.editFile" />
                      </div>
                    </div>
                    <div v-else class="text-sm text-gray-500">
                      <p>{{ speaker.file ? speaker.file.name : 'Drop audio sample or click to browse' }}</p>
                      <p v-if="!speaker.file" class="text-xs text-gray-400 mt-0.5">Optional — used for speaker identification</p>
                    </div>
                  </div>
                </div>
                <div class="flex flex-col gap-1.5 shrink-0">
                  <button
                    class="flex-1 text-xs px-3 rounded-md bg-indigo-600 text-white hover:bg-indigo-500 transition-colors"
                    @click="saveEdit(speaker)"
                  >
                    Save
                  </button>
                  <button
                    class="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-500 hover:border-gray-400 hover:text-gray-700 transition-colors"
                    @click="cancelEdit(speaker)"
                  >
                    Cancel
                  </button>
                  <button
                    class="text-xs px-3 py-1.5 rounded-md border border-red-300 text-red-500 hover:border-red-400 hover:text-red-600 transition-colors"
                    @click="removeSpeaker(speaker.localId)"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Add speaker block (collapsible) -->
        <div
          v-if="draftOpen"
          ref="draftContainer"
          class="border border-dashed border-gray-300 rounded-md p-2 bg-white"
          @focusout="handleDraftFocusOut"
        >
          <p class="text-xs font-medium text-gray-500 mb-1.5">
            {{ pendingSpeakers.length === 0 ? 'Add speaker' : 'New speaker' }}
          </p>
          <div class="flex gap-2 items-stretch">
            <div class="flex-1 flex flex-col gap-1.5">
              <input
                v-model="draftName"
                type="text"
                :placeholder="draftPlaceholder"
                class="w-full text-sm border border-gray-300 rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <div
                class="flex-1 border-2 border-dashed rounded-lg p-2 text-center cursor-pointer transition-colors"
                :class="draftIsDragOver ? 'border-indigo-400 bg-indigo-50' : draftFile ? 'border-green-300 bg-green-50' : 'border-gray-300 hover:border-gray-400'"
                @dragover.prevent="draftIsDragOver = true"
                @dragleave="draftIsDragOver = false"
                @drop.prevent="(e) => { draftIsDragOver = false; const f = e.dataTransfer?.files[0]; if (f) draftFile = f }"
                @click="draftFileInput?.click()"
              >
                <input
                  ref="draftFileInput"
                  type="file"
                  accept="audio/*"
                  class="hidden"
                  @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) draftFile = f }"
                />
                <div v-if="draftFile" class="text-sm text-gray-700">
                  <span class="font-medium">{{ draftFile.name }}</span>
                  <span class="text-gray-400 ml-2">({{ formatSize(draftFile.size) }})</span>
                  <div class="mt-2 pt-2 border-t border-green-200" @click.stop>
                    <AudioPlayer :file="draftFile" />
                  </div>
                </div>
                <div v-else class="text-sm text-gray-500">
                  <p>Drop audio sample or click to browse</p>
                  <p class="text-xs text-gray-400 mt-0.5">Optional — used for speaker identification</p>
                </div>
              </div>
            </div>
            <button
              :disabled="!draftName.trim() && !draftFile"
              class="text-xs px-3 rounded-md border border-gray-300 text-gray-600 hover:border-gray-400 hover:text-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0 self-stretch"
              @click="commitDraft"
            >
              + Add
            </button>
          </div>
        </div>

        <!-- "Add another speaker" link (shown when draft is collapsed) -->
        <button
          v-else
          class="mt-1 text-xs text-indigo-600 hover:text-indigo-500 transition-colors"
          @click="draftOpen = true"
        >
          + Add another speaker
        </button>

        <!-- Speaker count hint -->
        <div class="mt-3 pt-3 border-t border-gray-200">
          <label class="block text-xs font-medium text-gray-500 mb-1">Speaker count hint</label>
          <input
            v-model.number="speakerCountHint"
            type="number"
            min="1"
            max="30"
            class="w-full text-sm border border-gray-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>

      <!-- Language -->
      <div>
        <label class="block text-sm font-medium text-gray-600 mb-1">Language</label>
        <select
          v-model="language"
          class="w-full text-sm border border-gray-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option v-for="lang in LANGUAGES" :key="lang.code" :value="lang.code">
            {{ lang.label }}
          </option>
        </select>
      </div>
    </div>

    <!-- Submit -->
    <div class="mt-4">
      <button
        :disabled="!audioFile || uploading"
        class="w-full py-2 text-sm font-medium rounded-md bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        @click="handleSubmit"
      >
        <span v-if="uploading" class="flex items-center justify-center gap-2">
          <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Uploading…
        </span>
        <span v-else>Submit</span>
      </button>
      <p v-if="uploadError" class="mt-2 text-xs text-red-600">{{ uploadError }}</p>
    </div>

    <!-- Unsaved draft warning modal -->
    <Teleport to="body">
      <div
        v-if="showUnsavedWarning"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        @click.self="cancelWarning"
      >
        <div class="bg-white rounded-lg shadow-xl p-5 w-72 mx-4">
          <p class="text-sm font-semibold text-gray-800 mb-1">Unsaved speaker</p>
          <p class="text-xs text-gray-500 mb-4">
            You have an unsaved speaker
            <span v-if="draftName.trim()">"{{ draftName.trim() }}"</span>
            <span v-else>"{{ draftPlaceholder }}"</span>.
            Would you like to add them first?
          </p>
          <div class="flex gap-2 justify-end">
            <button
              class="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600 hover:border-gray-400 hover:text-gray-800 transition-colors"
              @click="cancelWarning"
            >
              Keep editing
            </button>
            <button
              class="text-xs px-3 py-1.5 rounded-md border border-red-200 text-red-500 hover:text-red-600 hover:border-red-300 transition-colors"
              @click="discardDraft"
            >
              Discard
            </button>
            <button
              class="text-xs px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-500 transition-colors"
              @click="confirmSaveDraft"
            >
              Add speaker
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

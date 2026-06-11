<script setup lang="ts">
import { ref } from "vue"
import AudioPlayer from "./AudioPlayer.vue"

const props = withDefaults(defineProps<{
  accept?: string
  maxSizeMb?: number
  label?: string
}>(), {
  accept: "audio/*",
  maxSizeMb: 2048,
  label: "Drop audio file or click to browse",
})

const emit = defineEmits<{
  "file-selected": [file: File]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const error = ref<string | null>(null)
const isDragOver = ref(false)
function handleFile(file: File) {
  error.value = null
  const maxBytes = props.maxSizeMb * 1024 * 1024
  if (file.size > maxBytes) {
    error.value = `File exceeds ${props.maxSizeMb} MB limit.`
    return
  }
  selectedFile.value = file
  emit("file-selected", file)
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) handleFile(file)
}

function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) handleFile(file)
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function setFile(file: File) {
  handleFile(file)
}

defineExpose({ setFile })
</script>

<template>
  <div>
    <div
      class="border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors"
      :class="isDragOver ? 'border-indigo-400 bg-indigo-50' : selectedFile ? 'border-green-300 bg-green-50 hover:border-green-400' : 'border-gray-300 hover:border-gray-400'"
      @dragover.prevent="isDragOver = true"
      @dragleave="isDragOver = false"
      @drop.prevent="onDrop"
      @click="fileInput?.click()"
    >
      <input
        ref="fileInput"
        type="file"
        :accept="accept"
        class="hidden"
        @change="onFileChange"
      />
      <div v-if="selectedFile" class="text-sm text-gray-700">
        <span class="font-medium">{{ selectedFile.name }}</span>
        <span class="text-gray-400 ml-2">({{ formatSize(selectedFile.size) }})</span>
        <div class="mt-2 pt-2 border-t border-green-200" @click.stop>
          <AudioPlayer :file="selectedFile" />
        </div>
      </div>
      <div v-else class="text-sm text-gray-500">
        <p>{{ label }}</p>
        <p class="text-xs text-gray-400 mt-1">(10 – 60 s, any audio format)</p>
      </div>
    </div>
    <p v-if="error" class="mt-1 text-xs text-red-600">{{ error }}</p>
  </div>
</template>

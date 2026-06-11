<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue"

const props = defineProps<{ file: File | null }>()

const audioEl = ref<HTMLAudioElement | null>(null)
const previewUrl = ref<string | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)

watch(() => props.file, (newFile, oldFile) => {
  if (oldFile && previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = newFile ? URL.createObjectURL(newFile) : null
  isPlaying.value = false
  currentTime.value = 0
  duration.value = 0
}, { immediate: true })

onUnmounted(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

function togglePlay() {
  if (!audioEl.value) return
  if (isPlaying.value) {
    audioEl.value.pause()
    isPlaying.value = false
  } else {
    audioEl.value.play()
    isPlaying.value = true
  }
}

function onTimeUpdate() {
  if (audioEl.value) currentTime.value = audioEl.value.currentTime
}

function onLoaded() {
  if (audioEl.value) duration.value = audioEl.value.duration
}

function onSeek(e: Event) {
  const val = Number((e.target as HTMLInputElement).value)
  if (audioEl.value) audioEl.value.currentTime = val
  currentTime.value = val
}

function formatTime(secs: number): string {
  if (!isFinite(secs)) return "0:00"
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}
</script>

<template>
  <div v-if="previewUrl" class="flex items-center gap-2">
    <audio
      ref="audioEl"
      :src="previewUrl"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoaded"
      @ended="isPlaying = false"
    />
    <button
      class="w-6 h-6 flex items-center justify-center rounded-full bg-green-600 hover:bg-green-500 text-white transition-colors shrink-0"
      @click="togglePlay"
    >
      <svg v-if="!isPlaying" class="w-3 h-3 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
        <path d="M8 5v14l11-7z"/>
      </svg>
      <svg v-else class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
        <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
      </svg>
    </button>
    <input
      type="range"
      :max="duration || 100"
      :value="currentTime"
      step="0.1"
      class="audio-scrubber flex-1"
      :style="{ '--progress': `${duration ? (currentTime / duration) * 100 : 0}%` }"
      @input="onSeek"
    />
    <span class="text-xs text-gray-500 tabular-nums shrink-0">
      {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
    </span>
  </div>
</template>

<style scoped>
.audio-scrubber {
  @apply appearance-none h-1 rounded-full outline-none cursor-pointer;
  background: linear-gradient(
    to right,
    #16a34a var(--progress, 0%),
    #bbf7d0 var(--progress, 0%)
  );
}
.audio-scrubber::-webkit-slider-thumb {
  @apply appearance-none w-3 h-3 rounded-full bg-green-600 cursor-pointer;
}
.audio-scrubber::-moz-range-thumb {
  @apply w-3 h-3 rounded-full bg-green-600 border-0 cursor-pointer;
}
</style>

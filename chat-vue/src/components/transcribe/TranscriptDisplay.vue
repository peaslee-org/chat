<script setup lang="ts">
import type { TranscriptResponse } from "@/types"
import { computed } from "vue"
import { speakerColor, type ComputedTurn } from "@/composables/useMatchingThresholds"

const props = defineProps<{
  transcript: TranscriptResponse
  computedTurns?: ComputedTurn[]
}>()

const allLabels = computed(() => (props.computedTurns ?? []).map(t => t.label))

const useHours = computed(() => {
  const turns = props.computedTurns
  if (turns?.length) return turns.some(t => t.end_time >= 3600)
  return props.transcript.segments.some(s => s.end_time >= 3600)
})

function formatTime(seconds: number): string {
  if (useHours.value) {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    return [h, m, s].map(n => String(n).padStart(2, '0')).join(':')
  }
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function downloadTranscript() {
  const lines = (props.computedTurns && props.computedTurns.length > 0
    ? props.computedTurns.map(t =>
        `[${t.start_time.toFixed(2)} - ${t.end_time.toFixed(2)}] ${t.label} [${t.matchType}]: ${t.text}`)
    : props.transcript.segments.map(s =>
        `[${s.start_time.toFixed(2)} - ${s.end_time.toFixed(2)}] ${s.speaker_name ?? s.anonymous_label}: ${s.text}`)
  ).join('\n')

  const blob = new Blob([lines], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'transcript.txt'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="mt-4">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-gray-700">Transcript</h3>
      <button
        v-if="transcript.segments.length > 0"
        @click="downloadTranscript"
        class="text-xs text-indigo-600 hover:text-indigo-500"
      >
        Download transcript.txt
      </button>
    </div>

    <!-- Dynamic mode: computed turns with match strength -->
    <div v-if="computedTurns && computedTurns.length > 0" class="space-y-0.5">
      <div
        v-for="(turn, i) in computedTurns"
        :key="i"
        class="flex gap-3 py-1 text-sm"
      >
        <span class="text-gray-400 font-mono flex-shrink-0">
          {{ formatTime(turn.start_time) }}-{{ formatTime(turn.end_time) }}
        </span>
        <span
          class="flex-shrink-0 w-24 truncate"
          :class="[
            speakerColor(turn.label, allLabels),
            turn.matchType === 'high' ? 'font-extrabold' :
            turn.matchType === 'medium' ? 'font-medium opacity-80' :
            turn.matchType === 'low' ? 'font-normal opacity-60' :
            'font-normal opacity-40 italic',
          ]"
        >{{ turn.label }}</span>
        <span class="text-gray-700">{{ turn.text }}</span>
      </div>
    </div>

    <!-- Static fallback: original segment display -->
    <div v-else class="space-y-0.5">
      <div
        v-for="segment in transcript.segments"
        :key="segment.segment_id"
        class="flex gap-3 py-1 text-sm"
      >
        <span class="text-gray-400 font-mono flex-shrink-0">
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
    </div>
  </div>
</template>

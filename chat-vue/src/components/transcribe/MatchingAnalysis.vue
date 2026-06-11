<script setup lang="ts">
import { ref, computed } from "vue"
import { useTranscribeStore } from "@/stores/transcribe"
import {
  useMatchingThresholds,
  computeTurns,
  speakerColor,
  type ComputedTurn,
} from "@/composables/useMatchingThresholds"

const props = defineProps<{ jobId: string }>()

const store = useTranscribeStore()
const { cosineDistThreshold, separationMin, qualityMin, confidenceMin } = useMatchingThresholds()

const isOpen = ref(false)
const isLoading = ref(false)

async function toggle() {
  isOpen.value = !isOpen.value
  if (isOpen.value && !store.turnDistanceData[props.jobId]) {
    isLoading.value = true
    try {
      await store.loadTurnDistances(props.jobId)
    } finally {
      isLoading.value = false
    }
  }
}

const computedTurns = computed((): ComputedTurn[] => {
  const turns = store.turnDistanceData[props.jobId]
  if (!turns) return []
  return computeTurns(turns, cosineDistThreshold.value, separationMin.value, qualityMin.value, confidenceMin.value)
})

const allLabels = computed(() => computedTurns.value.map(t => t.label))

const stats = computed(() => {
  const counts = { high: 0, medium: 0, low: 0, none: 0, total: computedTurns.value.length }
  for (const t of computedTurns.value) counts[t.matchType]++
  return counts
})

const useHours = computed(() =>
  computedTurns.value.some(t => t.end_time >= 3600)
)

function formatTime(s: number): string {
  if (useHours.value) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const sec = Math.floor(s % 60)
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
  }
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
}
</script>

<template>
  <div class="flex-shrink-0 border-t border-gray-200 bg-white">
    <button
      class="w-full px-4 py-3 flex items-center justify-between text-xs font-semibold text-gray-500 uppercase tracking-wide hover:bg-gray-50 transition-colors"
      @click="toggle"
    >
      <span>Matching Analysis</span>
      <span class="text-gray-400">{{ isOpen ? "▲" : "▼" }}</span>
    </button>

    <div v-if="isOpen" class="px-4 pb-4">
      <div v-if="isLoading" class="text-sm text-gray-400 text-center py-4">Loading…</div>
      <template v-else-if="!store.turnDistanceData[jobId] || store.turnDistanceData[jobId].length === 0">
        <p class="text-xs text-gray-400 text-center py-2">No distance data available for this job.</p>
      </template>
      <template v-else>
        <!-- Four threshold sliders -->
        <div class="grid grid-cols-2 gap-x-4 gap-y-3 mb-3">
          <div>
            <label class="text-xs text-gray-600 flex justify-between mb-0.5">
              <span>Cosine dist</span>
              <span class="font-mono text-gray-800">{{ cosineDistThreshold.toFixed(2) }}</span>
            </label>
            <input type="range" min="0" max="1.5" step="0.01" v-model.number="cosineDistThreshold" class="w-full accent-indigo-600" />
          </div>
          <div>
            <label class="text-xs text-gray-600 flex justify-between mb-0.5">
              <span>Separation min</span>
              <span class="font-mono text-gray-800">{{ separationMin.toFixed(2) }}</span>
            </label>
            <input type="range" min="0" max="1" step="0.01" v-model.number="separationMin" class="w-full accent-indigo-600" />
          </div>
          <div>
            <label class="text-xs text-gray-600 flex justify-between mb-0.5">
              <span>Quality min</span>
              <span class="font-mono text-gray-800">{{ qualityMin.toFixed(2) }}</span>
            </label>
            <input type="range" min="0" max="1" step="0.01" v-model.number="qualityMin" class="w-full accent-indigo-600" />
          </div>
          <div>
            <label class="text-xs text-gray-600 flex justify-between mb-0.5">
              <span>Confidence min</span>
              <span class="font-mono text-gray-800">{{ confidenceMin.toFixed(2) }}</span>
            </label>
            <input type="range" min="0" max="1" step="0.01" v-model.number="confidenceMin" class="w-full accent-indigo-600" />
          </div>
        </div>

        <!-- Stats bar -->
        <div class="text-xs text-gray-500 mb-2">
          <span class="font-bold text-gray-700">{{ stats.high }} high</span>
          · <span class="font-medium text-gray-600">{{ stats.medium }} medium</span>
          · <span class="text-gray-400">{{ stats.low }} low</span>
          · <span class="text-gray-300">{{ stats.none }} none</span>
          <span class="text-gray-300 ml-1">({{ stats.total }} turns)</span>
        </div>

        <!-- Turn list -->
        <div class="max-h-64 overflow-y-auto space-y-1">
          <div
            v-for="(turn, i) in computedTurns"
            :key="i"
            class="flex gap-2 text-xs"
          >
            <span class="text-gray-400 shrink-0 font-mono">{{ formatTime(turn.start_time) }}-{{ formatTime(turn.end_time) }}</span>
            <span
              class="shrink-0 truncate"
              :class="[
                speakerColor(turn.label, allLabels),
                turn.matchType === 'high' ? 'font-extrabold' :
                turn.matchType === 'medium' ? 'font-medium opacity-80' :
                turn.matchType === 'low' ? 'font-normal opacity-60' :
                'font-normal opacity-40 italic text-gray-500',
              ]"
            >{{ turn.label }}{{ turn.matchType === 'low' ? '?' : '' }}</span>
            <span class="text-gray-500 truncate">{{ turn.text }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

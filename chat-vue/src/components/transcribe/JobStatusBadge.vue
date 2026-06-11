<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from "vue"
import type { TranscriptionJob, JobLogEntry } from "@/types"

const props = defineProps<{
  status: TranscriptionJob['status']
  logs?: JobLogEntry[]
  workerPaused?: boolean
  isPolling?: boolean
}>()

const inFlight = computed(() => props.status === 'transcribing' || props.status === 'matching')
const isPaused  = computed(() => inFlight.value && !!props.workerPaused)
const isActivelyPolling = computed(() => inFlight.value && !!props.isPolling && !isPaused.value)
const displayLabel = computed(() => {
  if (isPaused.value) return 'paused'
  if (isActivelyPolling.value) return 'polling'
  return props.status
})

const open = ref(false)
const badgeRef = ref<HTMLElement | null>(null)
const flyoutStyle = ref<Record<string, string>>({})

function formatTime(isoStr: string): string {
  return new Date(isoStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function computePosition() {
  if (!badgeRef.value) return
  const rect = badgeRef.value.getBoundingClientRect()
  const flyoutWidth = 288 // w-72
  const flyoutMaxHeight = 256 // max-h-64
  const spaceBelow = window.innerHeight - rect.bottom - 8
  const left = Math.max(4, Math.min(rect.right - flyoutWidth, window.innerWidth - flyoutWidth - 4))
  if (spaceBelow >= flyoutMaxHeight || spaceBelow > window.innerHeight - rect.top - 8) {
    flyoutStyle.value = { top: `${rect.bottom + 4}px`, left: `${left}px` }
  } else {
    flyoutStyle.value = { bottom: `${window.innerHeight - rect.top + 4}px`, left: `${left}px` }
  }
}

function toggle(e: Event) {
  if (!props.logs?.length) return
  e.stopPropagation()
  open.value = !open.value
  if (open.value) nextTick(computePosition)
}

function handleOutsideClick(e: MouseEvent) {
  if (!open.value) return
  if (badgeRef.value?.contains(e.target as Node)) return
  open.value = false
}

onMounted(() => document.addEventListener('click', handleOutsideClick, true))
onUnmounted(() => document.removeEventListener('click', handleOutsideClick, true))
</script>

<template>
  <span ref="badgeRef" class="relative inline-flex">
    <span
      class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
      :class="{
        'bg-gray-100 text-gray-600': status === 'pending',
        'bg-amber-100 text-amber-700': isPaused,
        'bg-blue-100 text-blue-700': !isPaused && status === 'transcribing',
        'bg-purple-100 text-purple-700': !isPaused && status === 'matching',
        'bg-green-100 text-green-800': status === 'complete',
        'bg-red-100 text-red-700': status === 'failed',
        'cursor-pointer hover:brightness-95 select-none': logs?.length,
      }"
      @click="toggle"
    >
      <!-- pending: clock -->
      <svg v-if="status === 'pending'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <!-- in-flight: paused state — pause icon, no animation -->
      <svg v-else-if="isPaused" class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
        <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
      </svg>
      <!-- in-flight: actively polling — spinner with animation -->
      <svg v-else-if="isActivelyPolling" class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
      <!-- in-flight: idle between polls — spinner without animation -->
      <svg v-else-if="inFlight" class="w-3 h-3" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
      <!-- complete: checkmark -->
      <svg v-else-if="status === 'complete'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
      </svg>
      <!-- failed: X -->
      <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
      </svg>
      {{ displayLabel }}
      <!-- log indicator dot -->
      <span v-if="logs?.length" class="ml-0.5 w-1 h-1 rounded-full bg-current opacity-50" />
    </span>

    <!-- Flyout log panel -->
    <Teleport to="body">
      <div
        v-if="open && logs?.length"
        class="fixed z-[9999] w-72 bg-white border border-gray-200 rounded-lg shadow-xl overflow-hidden"
        :style="flyoutStyle"
        @click.stop
      >
        <div class="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50">
          <span class="text-xs font-semibold text-gray-600">Activity log</span>
          <button class="text-gray-400 hover:text-gray-600 text-xs leading-none" @click="open = false">✕</button>
        </div>
        <div class="overflow-y-auto max-h-56 font-mono text-[10px] leading-relaxed">
          <div
            v-for="(entry, i) in logs"
            :key="i"
            class="flex gap-2 px-3 py-1 border-b border-gray-50 last:border-0"
            :class="entry.error ? 'bg-red-50' : ''"
          >
            <span class="shrink-0 text-gray-400 tabular-nums">{{ formatTime(entry.ts) }}</span>
            <span
              class="shrink-0 w-3 font-bold"
              :class="entry.direction === 'request' ? 'text-blue-500' : entry.error ? 'text-red-500' : 'text-green-600'"
            >{{ entry.direction === 'request' ? '→' : '←' }}</span>
            <span class="truncate" :class="entry.error ? 'text-red-700' : 'text-gray-700'">
              {{ entry.label }}<span v-if="entry.detail" class="text-gray-400 ml-1">{{ entry.detail }}</span>
            </span>
          </div>
        </div>
      </div>
    </Teleport>
  </span>
</template>

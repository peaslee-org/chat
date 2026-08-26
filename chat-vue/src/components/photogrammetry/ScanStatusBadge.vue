<script setup lang="ts">
import { computed } from "vue"
import type { PhotogrammetryJobStatus, PhotogrammetryStage, WorkerState } from "@/types"
import { workerStateLabel } from "@/lib/workerState"

const props = defineProps<{
  status: PhotogrammetryJobStatus
  stage?: PhotogrammetryStage | null
  workerState?: WorkerState | null
  estimatedWaitSeconds?: number | null
  isPolling?: boolean
}>()

const inFlight = computed(() => props.status === "queued" || props.status === "processing")
const label = computed(() => {
  if (inFlight.value && props.workerState && props.workerState !== "running") {
    return workerStateLabel(props.workerState, props.estimatedWaitSeconds ?? undefined)
  }
  if (props.status === "processing" && props.stage) return `processing · ${props.stage}`
  return props.status
})
const classes = computed(() => ({
  pending: "bg-gray-200 text-gray-700",
  queued: "bg-amber-100 text-amber-800",
  processing: "bg-indigo-100 text-indigo-800",
  complete: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
}[props.status]))
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
    :class="classes"
  >
    <span v-if="inFlight" class="h-1.5 w-1.5 rounded-full bg-current" :class="{ 'animate-pulse': isPolling }" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import type { PhotogrammetryJob } from "@/types"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"

const props = defineProps<{
  job: PhotogrammetryJob
  isActive: boolean
}>()

const store = usePhotogrammetryStore()

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const isToday = date.toDateString() === new Date().toDateString()
  return isToday
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" })
}

async function handleDelete(e: Event) {
  e.stopPropagation()
  if (!window.confirm(`Delete "${props.job.name}"?`)) return
  await store.deleteJob(props.job.job_id)
}
</script>

<template>
  <button
    class="group w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-gray-700 transition-colors"
    :class="{ 'bg-gray-700': isActive }"
    @click="store.selectJob(job.job_id)"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="truncate text-gray-200">{{ job.name }}</span>
      <span class="invisible group-hover:visible text-gray-400 hover:text-red-400 text-xs shrink-0" @click.stop="handleDelete">✕</span>
    </div>
    <div class="mt-1 flex items-center justify-between gap-2 text-xs text-gray-400">
      <span>{{ formatDate(job.created_at) }} · {{ job.image_count }} photos</span>
      <ScanStatusBadge
        :status="job.status"
        :stage="job.stage"
        :worker-state="job.worker_state"
        :estimated-wait-seconds="job.estimated_wait_seconds"
        :is-polling="store.pollingActive.has(job.job_id)"
      />
    </div>
  </button>
</template>

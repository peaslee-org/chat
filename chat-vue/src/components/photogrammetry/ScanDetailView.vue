<script setup lang="ts">
import { computed } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"

defineProps<{ showNewJobForm: boolean }>()
defineEmits<{ "close-new-job-form": [] }>()

const store = usePhotogrammetryStore()
const job = computed(() => store.activeJob)
</script>

<template>
  <section class="flex flex-col bg-gray-50 text-gray-900">
    <div v-if="showNewJobForm" class="p-6 overflow-y-auto">
      <!-- NewScanForm mounts here in Task 10 -->
      <p class="text-sm text-gray-500">New scan form</p>
    </div>

    <div v-else-if="!job" class="flex flex-1 items-center justify-center text-sm text-gray-500">
      Select a scan or start a new one
    </div>

    <div v-else class="flex flex-1 flex-col overflow-hidden">
      <header class="flex items-center gap-3 border-b border-gray-200 bg-white px-6 py-3">
        <h2 class="truncate text-base font-semibold">{{ job.name }}</h2>
        <ScanStatusBadge :status="job.status" :stage="job.stage" :worker-state="job.worker_state" :estimated-wait-seconds="job.estimated_wait_seconds" />
        <span class="text-xs text-gray-500">{{ job.image_count }} photos</span>
        <span v-if="job.gpu_notice" class="ml-auto text-xs text-amber-700">{{ job.gpu_notice }}</span>
      </header>
      <div class="flex-1 overflow-auto p-6">
        <!-- Task 11: progress / viewer / error -->
        <p v-if="job.status === 'failed'" class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ job.error_message ?? "Reconstruction failed" }}</p>
        <p v-else class="text-sm text-gray-500">{{ job.status }}</p>
      </div>
    </div>
  </section>
</template>

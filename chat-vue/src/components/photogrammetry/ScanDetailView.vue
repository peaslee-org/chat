<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ScanStatusBadge from "./ScanStatusBadge.vue"
import StageStrip from "./StageStrip.vue"
import MeshViewer from "./MeshViewer.vue"
import NewScanForm from "./NewScanForm.vue"

defineProps<{ showNewJobForm: boolean }>()
const emit = defineEmits<{ "close-new-job-form": [] }>()

const store = usePhotogrammetryStore()
const job = computed(() => store.activeJob)
const meshUrl = ref<string | null>(null)
const hasPreviewDownload = ref(false)
const meshError = ref<string | null>(null)

watch(
  [() => job.value?.job_id, () => job.value?.status],
  async ([jobId, status]) => {
    meshUrl.value = null
    hasPreviewDownload.value = false
    meshError.value = null
    if (jobId && status === "complete") {
      try {
        const urls = await store.fetchMeshUrls(jobId)
        if (job.value?.job_id !== jobId) return
        meshUrl.value = urls.url
        hasPreviewDownload.value = urls.previewDownloadUrl !== null
      } catch {
        if (job.value?.job_id !== jobId) return
        meshError.value = "Could not load the mesh URL"
      }
    }
  },
  { immediate: true },
)

/**
 * Re-resolve the URL at click time (the store refreshes it within 30 s of expiry) so a tab
 * left open past the 15-minute presign never hands S3 a stale link. The URL is presigned
 * with Content-Disposition: attachment, so assigning it saves the file and leaves the page.
 */
async function download(which: "mesh" | "preview"): Promise<void> {
  const jobId = job.value?.job_id
  if (!jobId) return
  try {
    const urls = await store.fetchMeshUrls(jobId)
    const url = which === "mesh" ? urls.downloadUrl : urls.previewDownloadUrl
    if (url) window.location.assign(url)
  } catch {
    meshError.value = "Could not get a download link"
  }
}
</script>

<template>
  <section class="flex flex-col bg-gray-50 text-gray-900">
    <div v-if="showNewJobForm" class="p-6 overflow-y-auto">
      <NewScanForm @submitted="emit('close-new-job-form')" />
    </div>

    <div v-else-if="!job" class="flex flex-1 items-center justify-center text-sm text-gray-500">
      Select a scan or start a new one
    </div>

    <div v-else class="flex flex-1 flex-col overflow-hidden">
      <header class="flex items-center gap-3 border-b border-gray-200 bg-white px-6 py-3">
        <h2 class="truncate text-base font-semibold">{{ job.name }}</h2>
        <ScanStatusBadge :status="job.status" :stage="job.stage" :worker-state="job.worker_state" :estimated-wait-seconds="job.estimated_wait_seconds" />
        <span class="text-xs text-gray-500">{{ job.image_count }} photos</span>
        <span v-if="job.gpu_notice" class="text-xs text-amber-700">{{ job.gpu_notice }}</span>
        <div v-if="job.status === 'complete'" class="ml-auto flex shrink-0 items-center gap-2">
          <button
            type="button"
            class="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            :disabled="!meshUrl"
            @click="download('mesh')"
          >Download GLB</button>
          <button
            v-if="hasPreviewDownload"
            type="button"
            class="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
            @click="download('preview')"
          >Download preview</button>
        </div>
      </header>
      <div class="flex-1 overflow-auto p-6">
        <ul v-if="job.warnings.length" class="mb-4 space-y-1 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <li v-for="w in job.warnings" :key="w">⚠ {{ w }}</li>
        </ul>

        <template v-if="job.status === 'failed'">
          <p class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ job.error_message ?? "Reconstruction failed" }}</p>
        </template>

        <template v-else-if="job.status === 'complete'">
          <MeshViewer v-if="meshUrl" :src="meshUrl" :poster="job.preview_url" :mock="job.mock" />
          <p v-else-if="meshError" class="text-sm text-red-600">{{ meshError }}</p>
          <p v-else class="text-sm text-gray-500">Loading mesh…</p>
        </template>

        <template v-else>
          <div class="space-y-4">
            <StageStrip :status="job.status" :stage="job.stage" />
            <p class="text-sm text-gray-600">
              <span v-if="job.status === 'pending'">Waiting for uploads to finish…</span>
              <span v-else-if="job.status === 'queued'">Queued — waiting for a GPU worker.</span>
              <span v-else>Reconstructing…</span>
            </p>
            <img v-if="job.preview_url" :src="job.preview_url" alt="" class="max-h-64 rounded border border-gray-200" />
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

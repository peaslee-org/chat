<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { takeJobQuery } from "@/lib/jobQuery"
import RunSidebar from "@/components/transcribe/RunSidebar.vue"
import RunDetailView from "@/components/transcribe/RunDetailView.vue"
import GpuStatusBar from "@/components/transcribe/GpuStatusBar.vue"
import { useTranscribeStore } from "@/stores/transcribe"

const store = useTranscribeStore()
const route = useRoute()
const router = useRouter()
const showNewJobForm = ref(false)

const SIDEBAR_MIN = 160
const SIDEBAR_MAX = 480
const SIDEBAR_DEFAULT = 256

const sidebarWidth = ref(parseInt(localStorage.getItem("transcribeSidebarWidth") ?? "") || SIDEBAR_DEFAULT)
const isDragging = ref(false)

function onDrag(e: MouseEvent) {
  sidebarWidth.value = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX))
  localStorage.setItem("transcribeSidebarWidth", String(sidebarWidth.value))
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener("mousemove", onDrag)
  document.removeEventListener("mouseup", stopDrag)
}

function startDrag() {
  isDragging.value = true
  document.addEventListener("mousemove", onDrag)
  document.addEventListener("mouseup", stopDrag)
}

function handleNew() {
  showNewJobForm.value = !showNewJobForm.value
}

onUnmounted(stopDrag)

onMounted(async () => {
  await Promise.all([store.loadSpeakers(true), store.loadJobs(true)])
  const linked = takeJobQuery(route, router)   // ?job=<id> from the usage panel's Startups links
  if (linked) void store.selectJob(linked)
  store.resumePollingForActiveJobs()
  store.resumePollingForProcessingSamples()
})
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden">
    <GpuStatusBar />
    <div class="flex min-h-0 flex-1 overflow-hidden" :class="{ 'select-none': isDragging }">
      <RunSidebar
        :style="{ width: sidebarWidth + 'px' }"
        :show-new-job-form="showNewJobForm"
        @new="handleNew"
      />
      <div
        class="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-indigo-500"
        :class="isDragging ? 'bg-indigo-500' : 'bg-gray-700'"
        @mousedown.prevent="startDrag"
      />
      <div class="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <RunDetailView
          class="flex-1 overflow-hidden"
          :show-new-job-form="showNewJobForm"
          @close-new-job-form="showNewJobForm = false"
        />

        <!-- Toast notifications: top-right of the content pane -->
        <div class="absolute right-4 top-4 z-50 flex max-w-sm flex-col gap-2">
          <div
            v-for="toast in store.toasts"
            :key="toast.id"
            class="flex items-start gap-3 bg-red-700 text-white text-sm rounded-lg shadow-lg px-4 py-3"
          >
            <svg class="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M12 4a8 8 0 100 16 8 8 0 000-16z" />
            </svg>
            <span class="flex-1">{{ toast.message }}</span>
            <button class="text-white/70 hover:text-white shrink-0" @click="store.dismissToast(toast.id)">✕</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import ScanSidebar from "@/components/photogrammetry/ScanSidebar.vue"
import ScanDetailView from "@/components/photogrammetry/ScanDetailView.vue"
import GpuStatusBar from "@/components/transcribe/GpuStatusBar.vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"

const store = usePhotogrammetryStore()
const showNewJobForm = ref(false)

const SIDEBAR_MIN = 160
const SIDEBAR_MAX = 480
const SIDEBAR_DEFAULT = 256

const sidebarWidth = ref(parseInt(localStorage.getItem("scanSidebarWidth") ?? "") || SIDEBAR_DEFAULT)
const isDragging = ref(false)

function onDrag(e: MouseEvent) {
  sidebarWidth.value = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX))
  localStorage.setItem("scanSidebarWidth", String(sidebarWidth.value))
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

onUnmounted(stopDrag)
onMounted(async () => {
  await store.loadJobs(true)
  store.resumePollingForActiveJobs()
})
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden">
    <GpuStatusBar family="photogrammetry" />
    <div class="flex min-h-0 flex-1 overflow-hidden" :class="{ 'select-none': isDragging }">
      <ScanSidebar
        :style="{ width: sidebarWidth + 'px' }"
        :show-new-job-form="showNewJobForm"
        @new="showNewJobForm = !showNewJobForm"
      />
      <div
        class="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-indigo-500"
        :class="isDragging ? 'bg-indigo-500' : 'bg-gray-700'"
        @mousedown.prevent="startDrag"
      />
      <ScanDetailView
        class="flex-1 overflow-hidden"
        :show-new-job-form="showNewJobForm"
        @close-new-job-form="showNewJobForm = false"
      />
    </div>

    <Teleport to="body">
      <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        <div
          v-for="toast in store.toasts"
          :key="toast.id"
          class="flex items-start gap-3 bg-red-700 text-white text-sm rounded-lg shadow-lg px-4 py-3"
        >
          <span class="flex-1">{{ toast.message }}</span>
          <button class="text-white/70 hover:text-white shrink-0" @click="store.dismissToast(toast.id)">✕</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

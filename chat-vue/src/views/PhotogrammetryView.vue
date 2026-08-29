<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"
import ScanSidebar from "@/components/photogrammetry/ScanSidebar.vue"
import ScanDetailView from "@/components/photogrammetry/ScanDetailView.vue"
import GpuStatusBar from "@/components/transcribe/GpuStatusBar.vue"
import type { NewScanMode } from "@/components/photogrammetry/newScanMode"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"

const store = usePhotogrammetryStore()
const formMode = ref<NewScanMode>("closed")

function toggleNew() {
  formMode.value = formMode.value === "closed" ? "blank" : "closed"
}
function openSample() {
  formMode.value = formMode.value === "sample" ? "closed" : "sample"
}

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
        :form-mode="formMode"
        @new="toggleNew"
        @new-sample="openSample"
      />
      <div
        class="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-indigo-500"
        :class="isDragging ? 'bg-indigo-500' : 'bg-gray-700'"
        @mousedown.prevent="startDrag"
      />
      <div class="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <ScanDetailView
          class="flex-1 overflow-hidden"
          :form-mode="formMode"
          @close-new-job-form="formMode = 'closed'"
          @use-own-photos="formMode = 'blank'"
        />

        <!-- Toast notifications: top-right of the content pane -->
        <div class="absolute right-4 top-4 z-50 flex max-w-sm flex-col gap-2">
          <div
            v-for="toast in store.toasts"
            :key="toast.id"
            class="flex items-start gap-3 bg-red-700 text-white text-sm rounded-lg shadow-lg px-4 py-3"
          >
            <span class="flex-1">{{ toast.message }}</span>
            <button class="text-white/70 hover:text-white shrink-0" @click="store.dismissToast(toast.id)">✕</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

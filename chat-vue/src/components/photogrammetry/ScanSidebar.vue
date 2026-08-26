<script setup lang="ts">
import { ref } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import { useAuthStore } from "@/stores/auth"
import ScanJobCard from "./ScanJobCard.vue"

defineProps<{ showNewJobForm: boolean }>()
const emit = defineEmits<{ new: [] }>()

const store = usePhotogrammetryStore()
const auth = useAuthStore()
const sampleBusy = ref(false)

async function handleSample() {
  if (sampleBusy.value) return
  sampleBusy.value = true
  try { await store.submitSampleJob() } finally { sampleBusy.value = false }
}
</script>

<template>
  <aside class="flex flex-col bg-gray-900 text-white shrink-0 overflow-hidden">
    <!-- Chat / Transcribe / Scan nav tabs -->
    <nav class="flex border-b border-gray-700">
      <RouterLink to="/" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path === '/' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Chat</RouterLink>
      <RouterLink to="/transcribe" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/transcribe') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Transcribe</RouterLink>
      <RouterLink to="/photogrammetry" class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/photogrammetry') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'">Scan</RouterLink>
    </nav>

    <div class="p-4 border-b border-gray-700 flex gap-2">
      <button
        class="flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors"
        :class="showNewJobForm ? 'bg-gray-700 text-gray-300 hover:bg-gray-600' : 'bg-indigo-600 hover:bg-indigo-500 text-white'"
        @click="emit('new')"
      >{{ showNewJobForm ? "✕ Cancel" : "+ New scan" }}</button>
      <button
        class="py-2 px-3 rounded-lg text-sm font-medium bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
        :disabled="sampleBusy"
        title="Run the bundled sample photo set"
        @click="handleSample"
      >Sample</button>
    </div>

    <nav class="flex-1 overflow-y-auto p-2 space-y-1">
      <div v-if="store.jobs.length === 0" class="text-gray-400 text-xs p-2">No scans yet</div>
      <ScanJobCard
        v-for="job in store.jobs"
        :key="job.job_id"
        :job="job"
        :is-active="job.job_id === store.activeJobId && !showNewJobForm"
      />
    </nav>

    <div class="p-4 border-t border-gray-700">
      <button class="text-gray-400 hover:text-white text-xs transition-colors" @click="auth.logout()">Sign out</button>
    </div>
  </aside>
</template>

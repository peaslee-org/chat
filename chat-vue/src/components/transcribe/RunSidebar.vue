<script setup lang="ts">
import { useTranscribeStore } from "@/stores/transcribe"
import { useAuthStore } from "@/stores/auth"
import JobStatusBadge from "./JobStatusBadge.vue"

const props = defineProps<{
  showNewJobForm: boolean
}>()

const emit = defineEmits<{
  new: []
}>()

const store = useTranscribeStore()
const auth = useAuthStore()

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  return isToday
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" })
}

async function handleDelete(e: Event, jobId: string) {
  e.stopPropagation()
  if (!window.confirm("Delete this run?")) return
  await store.deleteJob(jobId)
}
</script>

<template>
  <aside class="flex flex-col bg-gray-900 text-white shrink-0 overflow-hidden">
    <!-- Chat / Transcribe / Scan nav tabs -->
    <nav class="flex border-b border-gray-700">
      <RouterLink
        to="/"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path === '/' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Chat
      </RouterLink>
      <RouterLink
        to="/transcribe"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/transcribe') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Transcribe
      </RouterLink>
      <RouterLink
        to="/photogrammetry"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/photogrammetry') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Scan
      </RouterLink>
    </nav>

    <!-- New run button -->
    <div class="p-4 border-b border-gray-700">
      <button
        class="w-full py-2 px-3 rounded-lg text-sm font-medium transition-colors"
        :class="showNewJobForm ? 'bg-gray-700 text-gray-300 hover:bg-gray-600' : 'bg-indigo-600 hover:bg-indigo-500 text-white'"
        @click="emit('new')"
      >
        {{ showNewJobForm ? "✕ Cancel" : "+ New Run" }}
      </button>
    </div>

    <!-- Runs list -->
    <nav class="flex-1 overflow-y-auto p-2 space-y-1">
      <div v-if="store.jobs.length === 0" class="text-gray-400 text-xs p-2">
        No runs yet
      </div>
      <button
        v-for="job in store.jobs"
        :key="job.job_id"
        class="group w-full text-left flex items-center justify-between px-3 py-2 rounded-lg text-sm hover:bg-gray-700 transition-colors"
        :class="{ 'bg-gray-700': job.job_id === store.activeJobId && !showNewJobForm }"
        @click="store.selectJob(job.job_id)"
      >
        <span class="grid min-w-0 flex-1" style="grid-template-columns: 1fr auto">
          <span class="truncate text-gray-200">{{ formatDate(job.created_at) }}</span>
          <span class="pl-2 self-center shrink-0">
            <JobStatusBadge :status="job.status" />
          </span>
        </span>
        <span
          class="invisible group-hover:visible text-gray-400 hover:text-red-400 ml-2 text-xs shrink-0"
          @click.stop="handleDelete($event, job.job_id)"
        >
          ✕
        </span>
      </button>
    </nav>

    <!-- Sign out -->
    <div class="p-4 border-t border-gray-700">
      <button
        class="text-gray-400 hover:text-white text-xs transition-colors"
        @click="auth.logout()"
      >
        Sign out
      </button>
    </div>
  </aside>
</template>

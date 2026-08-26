<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useGpuStore } from "@/stores/gpu"
import { workerStateLabel } from "@/lib/workerState"

const gpu = useGpuStore()
const showUsage = ref(false)
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null

const label = computed(() => workerStateLabel(gpu.state?.worker_state, gpu.state?.estimated_wait_seconds))
const idleIn = computed(() => {
  if (!gpu.idleOutAt || gpu.state?.worker_state !== "running") return null
  const s = Math.max(0, Math.floor((gpu.idleOutAt.getTime() - now.value) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
})
const dot = computed(() => ({
  running: "bg-green-500", starting: "bg-amber-400 animate-pulse", off: "bg-gray-500",
}[gpu.state?.worker_state ?? "off"]))

onMounted(() => { gpu.startPolling(); void gpu.refreshUsage(); clock = setInterval(() => (now.value = Date.now()), 1000) })
onUnmounted(() => { gpu.stopPolling(); if (clock) clearInterval(clock) })
</script>

<template>
  <div class="flex items-center gap-3 border-b border-gray-700 bg-gray-900 px-4 py-2 text-sm text-gray-200">
    <span class="inline-block h-2.5 w-2.5 rounded-full" :class="dot" />
    <span>{{ label }}<span v-if="idleIn"> · idle-out in {{ idleIn }}</span></span>
    <button
      class="rounded bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-500 disabled:opacity-50"
      :disabled="gpu.warming || gpu.state?.worker_state === 'starting'"
      :title="gpu.state?.worker_state === 'running' ? 'Extend the idle timer' : 'Start the GPU now so your first job does not wait'"
      @click="gpu.warm()"
    >{{ gpu.state?.worker_state === "running" ? "Keep warm" : "Warm it up" }}</button>
    <span v-if="gpu.error" class="text-amber-300">{{ gpu.error }}</span>
    <span v-else-if="gpu.state?.notice" class="text-amber-300">{{ gpu.state.notice }}</span>
    <button class="ml-auto text-gray-400 hover:text-gray-200" @click="showUsage = !showUsage">
      {{ showUsage ? "Hide usage" : "Usage" }}
    </button>
  </div>
  <div v-if="showUsage && gpu.usage" class="grid grid-cols-2 gap-x-6 gap-y-1 border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs text-gray-300 md:grid-cols-4">
    <div>Today: <b>{{ gpu.usage.today_hours.toFixed(2) }} h</b> / {{ gpu.usage.daily_cap_hours }} h</div>
    <div>Month: <b>{{ gpu.usage.month_hours.toFixed(2) }} h</b> / {{ gpu.usage.monthly_cap_hours }} h</div>
    <div>Est. cost: <b>${{ gpu.usage.estimated_month_cost_usd.toFixed(2) }}</b> <span class="text-gray-500">(estimate @ ${{ gpu.usage.hourly_rate_usd }}/h)</span></div>
    <div>Actual MTD: <b>{{ gpu.usage.actual_month_to_date_usd == null ? "—" : "$" + gpu.usage.actual_month_to_date_usd.toFixed(2) }}</b></div>
    <div class="col-span-full">Your warm-ups today: {{ gpu.usage.warms_today_for_user }} / {{ gpu.usage.warm_cap_per_user_per_day }} · {{ gpu.usage.sessions.length }} session(s) this month</div>
  </div>
</template>

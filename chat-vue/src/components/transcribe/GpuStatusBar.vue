<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useGpuStore } from "@/stores/gpu"
import { durationLabel, elapsedLabel, workerStateLabel } from "@/lib/workerState"
import type { GpuFamily, GpuSessionSummary } from "@/types"

const props = withDefaults(defineProps<{ family?: GpuFamily }>(), { family: "transcription" })
const showWarm = computed(() => props.family === "transcription")

const gpu = useGpuStore()
const showUsage = ref(false)
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null

const label = computed(() => {
  const s = gpu.state
  if (s?.worker_state === "starting") {
    const base = workerStateLabel("starting", gpu.remainingSeconds)
    return s.starting_since ? `${base} · ${elapsedLabel(s.starting_since, new Date(now.value))} elapsed` : base
  }
  return workerStateLabel(s?.worker_state, s?.estimated_wait_seconds)
})
const labelTitle = computed(() => {
  const s = gpu.state
  if (s?.worker_state !== "starting") return undefined
  return s.estimate_basis === "measured"
    ? `estimate: median of the last ${s.estimate_samples} starts`
    : "estimate: default, no starts measured yet"
})
const idleIn = computed(() => {
  if (!gpu.idleOutAt || gpu.state?.worker_state !== "running") return null
  const s = Math.max(0, Math.floor((gpu.idleOutAt.getTime() - now.value) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
})
const dot = computed(() => ({
  running: "bg-green-500", starting: "bg-amber-400 animate-pulse", off: "bg-gray-500",
}[gpu.state?.worker_state ?? "off"]))

// ── startups: promised vs actual, newest first ──
const MAX_STARTUPS = 10
const startups = computed<GpuSessionSummary[]>(() =>
  (gpu.usage?.sessions ?? [])
    .filter(s => s.actual_startup_seconds !== null)
    .sort((a, b) => b.started_at.localeCompare(a.started_at))
    .slice(0, MAX_STARTUPS),
)
function delta(s: GpuSessionSummary): { text: string; late: boolean } | null {
  if (s.actual_startup_seconds === null || s.estimated_startup_seconds === null) return null
  const d = s.actual_startup_seconds - s.estimated_startup_seconds
  return { text: `${d < 0 ? "-" : "+"}${durationLabel(Math.abs(d))}`, late: d > 60 }
}
function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

onMounted(() => { gpu.startPolling(props.family); void gpu.refreshUsage(); clock = setInterval(() => (now.value = Date.now()), 1000) })
onUnmounted(() => { gpu.stopPolling(); if (clock) clearInterval(clock) })
</script>

<template>
  <div class="flex items-center gap-3 border-b border-gray-700 bg-gray-900 px-4 py-2 text-sm text-gray-200">
    <span class="inline-block h-2.5 w-2.5 rounded-full" :class="dot" />
    <span data-testid="gpu-label" :title="labelTitle">{{ label }}<span v-if="idleIn"> · idle-out in {{ idleIn }}</span></span>
    <button
      v-if="showWarm"
      class="rounded bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-500 disabled:opacity-50"
      :disabled="gpu.warming || gpu.state?.worker_state === 'starting'"
      :title="gpu.state?.worker_state === 'running' ? 'Extend the idle timer' : 'Start the GPU now so your first job does not wait'"
      @click="gpu.warm()"
    >{{ gpu.state?.worker_state === "running" ? "Keep warm" : "Warm it up" }}</button>
    <span v-if="gpu.error" class="text-amber-300">{{ gpu.error }}</span>
    <span v-else-if="gpu.state?.notice" class="text-amber-300">{{ gpu.state.notice }}</span>
    <button data-testid="usage-toggle" class="ml-auto text-gray-400 hover:text-gray-200" @click="showUsage = !showUsage">
      {{ showUsage ? "Hide usage" : "Usage" }}
    </button>
  </div>
  <div v-if="showUsage && gpu.usage" class="border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs text-gray-300">
    <div class="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
      <div>Today: <b>{{ gpu.usage.today_hours.toFixed(2) }} h</b> / {{ gpu.usage.daily_cap_hours }} h</div>
      <div>Month: <b>{{ gpu.usage.month_hours.toFixed(2) }} h</b> / {{ gpu.usage.monthly_cap_hours }} h</div>
      <div>Est. cost: <b>${{ gpu.usage.estimated_month_cost_usd.toFixed(2) }}</b> <span class="text-gray-500">(estimate @ ${{ gpu.usage.hourly_rate_usd }}/h)</span></div>
      <div>Actual MTD: <b>{{ gpu.usage.actual_month_to_date_usd == null ? "—" : "$" + gpu.usage.actual_month_to_date_usd.toFixed(2) }}</b></div>
      <div class="col-span-full">Your warm-ups today: {{ gpu.usage.warms_today_for_user }} / {{ gpu.usage.warm_cap_per_user_per_day }} · {{ gpu.usage.sessions.length }} session(s) this month</div>
    </div>

    <div data-testid="startups" class="mt-2 border-t border-gray-800 pt-2">
      <div class="text-gray-400">
        Startups —
        <span v-if="gpu.usage.startup_median_seconds !== null">
          median <b class="text-gray-200">{{ durationLabel(gpu.usage.startup_median_seconds) }}</b> over {{ gpu.usage.startup_samples }} starts
        </span>
        <span v-else>no measured starts yet</span>
        <span class="text-gray-500"> · launch → first job picked up</span>
      </div>
      <table v-if="startups.length" class="mt-1 w-full max-w-xl text-left tabular-nums">
        <thead class="text-gray-500">
          <tr><th class="pr-4 font-normal">When</th><th class="pr-4 font-normal">Promised</th><th class="pr-4 font-normal">Actual</th><th class="font-normal">Δ</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in startups" :key="s.started_at">
            <td class="pr-4">{{ when(s.started_at) }}</td>
            <td class="pr-4">{{ s.estimated_startup_seconds === null ? "—" : durationLabel(s.estimated_startup_seconds) }}</td>
            <td class="pr-4">{{ durationLabel(s.actual_startup_seconds!) }}</td>
            <td data-testid="delta" :class="delta(s)?.late ? 'text-red-400' : 'text-gray-300'">{{ delta(s)?.text ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

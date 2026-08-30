<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { RouterLink } from "vue-router"
import { useGpuStore } from "@/stores/gpu"
import { durationLabel, elapsedLabel, workerStateLabel } from "@/lib/workerState"
import type { GpuFamily, GpuSessionJob, GpuSessionSummary } from "@/types"

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
  const kind = s.start_kind === "warm" ? "warm start (instance still up)" : "cold start (new instance)"
  return s.estimate_basis === "measured"
    ? `${kind} · estimate: median of the last ${s.estimate_samples} ${s.start_kind} starts`
    : `${kind} · estimate: default, no ${s.start_kind} starts measured yet`
})
const idleIn = computed(() => {
  if (!gpu.idleOutAt || gpu.state?.worker_state !== "running") return null
  const s = Math.max(0, Math.floor((gpu.idleOutAt.getTime() - now.value) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
})
const dot = computed(() => ({
  running: "bg-green-500", starting: "bg-amber-400 animate-pulse", off: "bg-gray-500",
}[gpu.state?.worker_state ?? "off"]))

// ── startups: promised vs actual with per-stage timings, newest first; collapsed by default ──
// Only this page's family: the medians in the summary line are the family's too.
const MAX_STARTUPS = 5
const STARTUPS_OPEN_KEY = "gpuStartupsOpen"
function readStartupsOpen(): boolean {
  try { return localStorage.getItem(STARTUPS_OPEN_KEY) === "1" } catch { return false }
}
const startupsOpen = ref(readStartupsOpen())
function toggleStartups(): void {
  startupsOpen.value = !startupsOpen.value
  try { localStorage.setItem(STARTUPS_OPEN_KEY, startupsOpen.value ? "1" : "0") } catch { /* private mode etc. */ }
}
const startupsSummary = computed(() => {
  const u = gpu.usage
  if (!u) return ""
  const parts: string[] = []
  if (u.cold_median_seconds !== null) parts.push(`cold ~${durationLabel(u.cold_median_seconds)} (${u.cold_samples})`)
  if (u.warm_median_seconds !== null) parts.push(`warm ~${durationLabel(u.warm_median_seconds)} (${u.warm_samples})`)
  return parts.length ? parts.join(" · ") : "no measured starts yet"
})
const STAGES = ["capacity", "boot", "pull", "container", "init"] as const
function stage(s: GpuSessionSummary, key: (typeof STAGES)[number]): string {
  const v = s.stages?.[key]
  return v == null ? "—" : durationLabel(v)
}
const startups = computed<GpuSessionSummary[]>(() =>
  (gpu.usage?.sessions ?? [])
    .filter(s => s.actual_startup_seconds !== null && s.family === props.family)
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
/** Scan → its name; transcript → its time (it has no name). The page's ?job= opens it. */
function jobLabel(job: GpuSessionJob): string {
  return job.name ?? `Transcript ${when(job.created_at)}`
}
function jobLink(family: GpuFamily, job: GpuSessionJob): { path: string; query: { job: string } } {
  return { path: family === "photogrammetry" ? "/photogrammetry" : "/transcribe", query: { job: job.id } }
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
      <button
        type="button"
        data-testid="startups-toggle"
        class="flex items-center gap-2 text-gray-400 hover:text-gray-200"
        :aria-expanded="startupsOpen ? 'true' : 'false'"
        @click="toggleStartups"
      >
        <span class="inline-block w-3 transition-transform" :class="startupsOpen ? 'rotate-90' : ''">▸</span>
        <span>Startups</span>
        <span class="text-gray-200">{{ startupsSummary }}</span>
        <span class="text-gray-500">· launch → first job picked up</span>
      </button>
      <table v-if="startupsOpen && startups.length" class="mt-1 w-full max-w-4xl text-left tabular-nums">
        <thead class="text-gray-500">
          <tr>
            <th class="pr-3 font-normal">Job</th>
            <th class="pr-3 font-normal">When</th>
            <th class="pr-3 font-normal">Kind</th>
            <th class="pr-3 font-normal" title="RunTask → instance booted">Capacity</th>
            <th class="pr-3 font-normal" title="instance booted → image pull started">Boot</th>
            <th class="pr-3 font-normal" title="image pull">Pull</th>
            <th class="pr-3 font-normal" title="pull finished → task running">Container</th>
            <th class="pr-3 font-normal" title="task running → first job claimed">Init</th>
            <th class="pr-3 font-normal">Total</th>
            <th class="pr-3 font-normal">Promised</th>
            <th class="font-normal">Δ</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in startups" :key="s.started_at">
            <td class="max-w-[16rem] truncate pr-3" data-testid="job">
              <RouterLink v-if="s.job" :to="jobLink(s.family, s.job)" class="text-indigo-300 hover:underline" :title="jobLabel(s.job)">{{ jobLabel(s.job) }}</RouterLink>
              <span v-else>—</span>
            </td>
            <td class="pr-3">{{ when(s.started_at) }}</td>
            <td class="pr-3" data-testid="kind">
              <span
                v-if="s.kind"
                class="rounded-full px-1.5 text-[10px] uppercase"
                :class="s.kind === 'warm' ? 'bg-amber-900/60 text-amber-200' : 'bg-sky-900/60 text-sky-200'"
              >{{ s.kind }}</span>
              <span v-else>—</span>
            </td>
            <td v-for="k in STAGES" :key="k" class="pr-3">{{ stage(s, k) }}</td>
            <td class="pr-3">{{ durationLabel(s.actual_startup_seconds!) }}</td>
            <td class="pr-3">{{ s.estimated_startup_seconds === null ? "—" : durationLabel(s.estimated_startup_seconds) }}</td>
            <td data-testid="delta" :class="delta(s)?.late ? 'text-red-400' : 'text-gray-300'">{{ delta(s)?.text ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="startupsOpen" class="mt-1 text-gray-500">No measured starts to show.</p>
    </div>
  </div>
</template>

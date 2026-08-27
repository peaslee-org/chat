import { defineStore } from "pinia"
import { computed, ref } from "vue"
import axios from "axios"
import * as api from "@/lib/gpuApi"
import type { GpuFamily, GpuState, GpuUsage } from "@/types"

const STATE_POLL_MS = 30_000

export const useGpuStore = defineStore("gpu", () => {
  const state = ref<GpuState | null>(null)
  const usage = ref<GpuUsage | null>(null)
  const warming = ref(false)
  const error = ref<string | null>(null)
  const family = ref<GpuFamily>("transcription")
  let timer: ReturnType<typeof setTimeout> | null = null
  let polling = false
  // Bumped every time polling starts or stops so an in-flight request from a stale
  // family/generation can recognize it's obsolete when its response lands and drop it
  // instead of overwriting state.value or re-arming setTimeout.
  let generation = 0

  const idleOutAt = computed(() => (state.value?.warm_until ? new Date(state.value.warm_until) : null))

  async function refreshState(f: GpuFamily = family.value) {
    try { state.value = await api.getGpuState(f); error.value = null }
    catch (e) { if (!(axios.isAxiosError(e) && e.response?.status === 503)) error.value = "GPU status unavailable" }
  }
  async function refreshUsage() {
    try { usage.value = await api.getGpuUsage() } catch { /* panel shows nothing */ }
  }
  async function warm() {
    warming.value = true
    try {
      state.value = await api.warmGpu(family.value); error.value = null
      await refreshUsage()
    } catch (e) {
      error.value = axios.isAxiosError(e) && e.response?.status === 429
        ? String(e.response.data?.detail ?? "GPU budget used")
        : "Could not warm the GPU"
    } finally { warming.value = false }
  }
  function startPolling(f: GpuFamily = "transcription") {
    stopPolling()
    generation += 1
    const gen = generation
    family.value = f
    state.value = null
    polling = true
    const tick = async () => {
      try {
        const s = await api.getGpuState(f)
        // A family switch or unmount since this request went out bumped `generation` —
        // drop the response instead of overwriting state.value with the stale family's
        // data or rescheduling a second, now-orphaned polling loop.
        if (gen !== generation) return
        state.value = s
        error.value = null
      } catch (e) {
        if (gen !== generation) return
        if (!(axios.isAxiosError(e) && e.response?.status === 503)) error.value = "GPU status unavailable"
      }
      if (gen !== generation || !polling) return
      timer = setTimeout(tick, STATE_POLL_MS)
    }
    void tick()
  }
  function stopPolling() {
    polling = false
    generation += 1
    if (timer) { clearTimeout(timer); timer = null }
  }

  return { state, usage, warming, error, family, idleOutAt, refreshState, refreshUsage, warm, startPolling, stopPolling }
})

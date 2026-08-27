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

  const idleOutAt = computed(() => (state.value?.warm_until ? new Date(state.value.warm_until) : null))

  async function refreshState() {
    try { state.value = await api.getGpuState(family.value); error.value = null }
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
    family.value = f
    state.value = null
    polling = true
    const tick = async () => {
      await refreshState()
      // stopPolling() may have run while the request above was in flight — timer was
      // null at that instant so it couldn't cancel us; re-check the flag before
      // rescheduling so we don't resurrect the loop after the component unmounted.
      if (!polling) return
      timer = setTimeout(tick, STATE_POLL_MS)
    }
    void tick()
  }
  function stopPolling() {
    polling = false
    if (timer) { clearTimeout(timer); timer = null }
  }

  return { state, usage, warming, error, family, idleOutAt, refreshState, refreshUsage, warm, startPolling, stopPolling }
})

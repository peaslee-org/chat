<script setup lang="ts">
import "@google/model-viewer"
import { ref, watch } from "vue"

const props = withDefaults(defineProps<{
  src?: string | null
  poster?: string | null
  mock: boolean
  /** True while the presigned URL is still being resolved — shows the shell and a 0 % pill. */
  pending?: boolean
}>(), { src: null, poster: null, pending: false })

const progress = ref(0)
const loaded = ref(false)
const failed = ref(false)

// Listeners are bound in the template (Vue attaches native listeners to the custom element),
// so they exist however late <model-viewer> appears — after `pending`, or for a new `src`.
function onProgress(e: Event) {
  const total = (e as CustomEvent<{ totalProgress?: number }>).detail?.totalProgress
  if (typeof total === "number") progress.value = total
}
function onLoad() { loaded.value = true }
function onError() { failed.value = true }

// A different mesh (another scan selected) starts over from "Loading mesh… 0%".
watch(() => props.src, () => {
  progress.value = 0
  loaded.value = false
  failed.value = false
})
</script>

<template>
  <div class="flex h-full flex-col">
    <p v-if="mock" class="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      Placeholder mesh — served by the local mock, not reconstructed from these photos.
    </p>
    <div class="relative min-h-[360px] w-full flex-1">
      <model-viewer
        v-if="!props.pending && props.src"
        :src="props.src"
        :poster="props.poster ?? undefined"
        camera-controls
        auto-rotate
        shadow-intensity="1"
        alt="Reconstructed mesh"
        class="h-full min-h-[360px] w-full rounded-lg bg-gray-900"
        @progress="onProgress"
        @load="onLoad"
        @error="onError"
      />
      <div v-else class="h-full min-h-[360px] w-full rounded-lg bg-gray-900" />

      <span
        v-if="failed"
        data-testid="mesh-pill"
        class="absolute left-3 top-3 rounded-full bg-red-700/90 px-3 py-1 text-xs text-white shadow"
      >Couldn't load the mesh</span>
      <span
        v-else-if="props.pending || !loaded"
        data-testid="mesh-pill"
        class="absolute left-3 top-3 rounded-full bg-black/70 px-3 py-1 text-xs text-white shadow"
      >Loading mesh… {{ Math.round((props.pending ? 0 : progress) * 100) }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import "@google/model-viewer"

defineProps<{
  src: string
  poster?: string | null
  mock: boolean
}>()
</script>

<template>
  <div class="flex h-full flex-col">
    <p v-if="mock" class="mb-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      Placeholder mesh — served by the local mock, not reconstructed from these photos.
    </p>
    <model-viewer
      :src="src"
      :poster="poster ?? undefined"
      camera-controls
      auto-rotate
      shadow-intensity="1"
      alt="Reconstructed mesh"
      class="min-h-[360px] w-full flex-1 rounded-lg bg-gray-900"
    />
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue"
import type { PhotoItem } from "@/types"

/**
 * Dense thumbnail grid over a scan's input photos. Thumbnails are ≤256 px JPEGs served by the
 * API, so a 150-photo set is a few MB, lazily; the full-size original loads only when a
 * thumbnail is clicked (overlay). Shared by the scan page and the New Scan form's sample mode.
 */
const props = withDefaults(defineProps<{
  photos: PhotoItem[]
  loading?: boolean
  error?: string | null
}>(), { loading: false, error: null })

const emit = defineEmits<{ open: [photo: PhotoItem] }>()

const SKELETON_COUNT = 24
const open = ref<PhotoItem | null>(null)

function show(photo: PhotoItem) {
  open.value = photo
  emit("open", photo)
}

function close() {
  open.value = null
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") close()
}

watch(open, (photo, prev) => {
  if (photo && !prev) document.addEventListener("keydown", onKeydown)
  else if (!photo && prev) document.removeEventListener("keydown", onKeydown)
})

onUnmounted(() => document.removeEventListener("keydown", onKeydown))
</script>

<template>
  <div>
    <p v-if="props.error" class="text-sm text-red-600">{{ props.error }}</p>

    <div v-else-if="props.loading" class="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-1">
      <div v-for="i in SKELETON_COUNT" :key="i" data-testid="skeleton" class="aspect-square animate-pulse rounded bg-gray-200" />
    </div>

    <div v-else class="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-1">
      <button
        v-for="photo in props.photos"
        :key="photo.filename"
        type="button"
        class="aspect-square overflow-hidden rounded bg-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        @click="show(photo)"
      >
        <img
          :src="photo.thumb_url"
          :alt="photo.filename"
          :title="photo.filename"
          loading="lazy"
          decoding="async"
          class="h-full w-full object-cover transition-transform hover:scale-105"
        />
      </button>
    </div>

    <div
      v-if="open"
      data-testid="photo-overlay"
      class="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/80 p-4"
      @click="close"
    >
      <img :src="open.url" :alt="open.filename" class="max-h-[90vh] max-w-full rounded object-contain" @click.stop />
      <p class="mt-2 text-sm text-white/80">{{ open.filename }}</p>
      <button
        type="button"
        class="absolute right-4 top-4 rounded-full bg-black/60 px-3 py-1 text-sm text-white hover:bg-black/80"
        aria-label="Close"
        @click.stop="close"
      >✕</button>
    </div>
  </div>
</template>

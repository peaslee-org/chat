<script setup lang="ts">
import { computed } from "vue"
import type { PhotogrammetryJobStatus, PhotogrammetryStage } from "@/types"

const props = defineProps<{ status: PhotogrammetryJobStatus; stage: PhotogrammetryStage | null }>()

const STEPS: { key: PhotogrammetryStage; label: string }[] = [
  { key: "sfm", label: "Cameras (SfM)" },
  { key: "dense", label: "Dense cloud" },
  { key: "mesh", label: "Mesh" },
  { key: "texture", label: "Texture" },
]

const currentIdx = computed(() => {
  if (props.status === "complete") return STEPS.length
  if (props.status !== "processing" || !props.stage) return -1
  return STEPS.findIndex(s => s.key === props.stage)
})
</script>

<template>
  <ol class="flex items-center gap-2 text-xs">
    <li v-for="(s, i) in STEPS" :key="s.key" class="flex items-center gap-2">
      <span
        class="flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold"
        :class="i < currentIdx ? 'border-green-500 bg-green-500 text-white'
              : i === currentIdx ? 'border-indigo-500 bg-indigo-500 text-white animate-pulse'
              : 'border-gray-300 text-gray-400'"
      >{{ i + 1 }}</span>
      <span :class="i <= currentIdx ? 'text-gray-800' : 'text-gray-400'">{{ s.label }}</span>
      <span v-if="i < STEPS.length - 1" class="h-px w-6 bg-gray-300" />
    </li>
  </ol>
</template>

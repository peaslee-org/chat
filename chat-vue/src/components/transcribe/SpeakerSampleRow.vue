<script setup lang="ts">
import type { SpeakerSample } from "@/types"
import SampleStatusBadge from "./SampleStatusBadge.vue"

defineProps<{
  sample: SpeakerSample
  speakerName: string
}>()

const emit = defineEmits<{
  delete: []
}>()

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString([], { month: 'numeric', day: 'numeric', year: 'numeric' })
}
</script>

<template>
  <div class="py-1 text-xs text-gray-600">
    <div class="flex items-center gap-2">
      <span class="text-gray-400">●</span>
      <span class="text-gray-500">{{ formatDate(sample.created_at) }}</span>
      <span v-if="sample.duration_seconds !== null" class="text-gray-500">
        {{ sample.duration_seconds.toFixed(1) }}s
      </span>
      <SampleStatusBadge :status="sample.status" />
      <button
        class="ml-auto text-gray-400 hover:text-red-500 transition-colors"
        @click="emit('delete')"
      >
        Remove
      </button>
    </div>
    <p v-if="sample.status === 'failed' && sample.error_message" class="mt-0.5 pl-4 text-red-500 break-words">
      {{ sample.error_message }}
    </p>
    <p v-else-if="sample.status === 'failed'" class="mt-0.5 pl-4 text-red-500">
      Embedding failed — please re-upload. (ID: {{ sample.sample_id.slice(0, 8) }})
    </p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  status: 'processing' | 'ready' | 'failed'
}>()
</script>

<template>
  <span
    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
    :class="{
      'bg-yellow-100 text-yellow-800': status === 'processing',
      'bg-green-100 text-green-800': status === 'ready',
      'bg-red-100 text-red-800': status === 'failed',
    }"
  >
    <svg
      v-if="status === 'processing'"
      class="w-3 h-3 animate-spin"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
    <svg v-else-if="status === 'ready'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
    </svg>
    <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
    </svg>
    {{ status }}
  </span>
</template>

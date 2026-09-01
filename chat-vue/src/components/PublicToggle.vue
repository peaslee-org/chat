<script setup lang="ts">
defineProps<{ isPublic: boolean; busy?: boolean }>()
const emit = defineEmits<{ toggle: [next: boolean] }>()
</script>

<template>
  <button
    type="button"
    class="rounded border px-2.5 py-1 text-xs font-medium disabled:opacity-50"
    :class="isPublic ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'"
    :disabled="busy"
    :title="isPublic ? 'Shown on the public demo page — click to make private' : 'Private — click to show on the public demo page'"
    data-testid="public-toggle"
    @click="emit('toggle', !isPublic)"
  >{{ isPublic ? 'Public' : 'Make public' }}</button>
</template>

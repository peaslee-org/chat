<template>
  <div
    class="flex"
    :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
  >
    <div
      class="max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap"
      :class="
        message.role === 'user'
          ? 'bg-indigo-600 text-white rounded-br-sm'
          : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm'
      "
    >
      {{ message.content }}
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Message } from '@/types'

defineProps<{ message: Message }>()
</script>

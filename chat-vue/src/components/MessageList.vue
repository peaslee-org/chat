<template>
  <div ref="listEl" class="flex-1 overflow-y-auto p-6 space-y-4">
    <div v-if="messages.length === 0" class="text-gray-400 text-sm text-center mt-20">
      Start a conversation
    </div>
    <MessageBubble
      v-for="msg in messages"
      :key="msg.id"
      :message="msg"
    />
    <div v-if="isSending" class="flex gap-2 items-end">
      <div class="bg-gray-200 rounded-2xl px-4 py-3 text-sm text-gray-500">
        <span class="animate-pulse">Thinking...</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { Message } from '@/types'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{
  messages: Message[]
  isSending: boolean
}>()

const listEl = ref<HTMLDivElement | null>(null)

watch(
  () => [props.messages.length, props.isSending],
  async () => {
    await nextTick()
    if (listEl.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
    }
  }
)
</script>

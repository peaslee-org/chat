<template>
  <aside class="flex flex-col bg-gray-900 text-white shrink-0 overflow-hidden">
    <!-- Chat / Transcribe nav tabs -->
    <nav class="flex border-b border-gray-700">
      <RouterLink
        to="/"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path === '/' ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Chat
      </RouterLink>
      <RouterLink
        to="/transcribe"
        class="flex-1 py-2 text-center text-sm font-medium transition-colors"
        :class="$route.path.startsWith('/transcribe') ? 'text-indigo-400 border-b-2 border-indigo-400' : 'text-gray-400 hover:text-gray-200'"
      >
        Transcribe
      </RouterLink>
    </nav>

    <div v-if="conversations.length > 0 || isLoading" class="p-4 border-b border-gray-700">
      <button
        class="w-full py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors"
        @click="emit('new')"
      >
        + New Chat
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto p-2 space-y-1">
      <div v-if="isLoading" class="text-gray-400 text-xs p-2">Loading...</div>
      <button
        v-for="conv in conversations"
        :key="conv.id"
        class="group w-full text-left flex items-center justify-between px-3 py-2 rounded-lg text-sm hover:bg-gray-700 transition-colors"
        :class="{ 'bg-gray-700': conv.id === activeId }"
        @click="emit('select', conv.id)"
      >
        <span class="grid min-w-0 flex-1" style="grid-template-columns: 1fr auto">
          <span class="truncate">{{ conv.title ?? '[No title]' }}</span>
          <span class="text-gray-500 text-xs pl-2 text-right self-center">{{ formatDate(conv.created_at) }}</span>
        </span>
        <span
          class="invisible group-hover:visible text-gray-400 hover:text-red-400 ml-1 text-xs shrink-0"
          @click.stop="emit('delete', conv.id)"
        >
          ✕
        </span>
      </button>
    </nav>

    <div class="p-4 border-t border-gray-700 flex items-center justify-between">
      <button
        class="text-gray-400 hover:text-white text-xs transition-colors"
        @click="emit('logout')"
      >
        Sign out
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { Conversation } from '@/types'

withDefaults(defineProps<{
  conversations?: Conversation[]
  activeId?: string | null
  isLoading?: boolean
}>(), {
  conversations: () => [],
  activeId: null,
  isLoading: false,
})

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  return isToday
    ? date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const emit = defineEmits<{
  select: [id: string]
  new: []
  delete: [id: string]
  logout: []
}>()
</script>

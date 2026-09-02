<template>
  <div class="flex h-screen overflow-hidden" :class="{ 'select-none': isDragging }">
    <ConversationSidebar
      :style="{ width: sidebarWidth + 'px' }"
      :conversations="chat.conversations"
      :active-id="chat.activeConversationId"
      :is-loading="chat.isLoading"
      @select="chat.selectConversation"
      @new="chat.startNewConversation"
      @delete="chat.deleteConversation"
      @logout="auth.logout"
      @set-visibility="chat.setConversationVisibility"
    />
    <div
      class="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-indigo-500"
      :class="isDragging ? 'bg-indigo-500' : 'bg-gray-700'"
      @mousedown.prevent="startDrag"
    />

    <div class="flex flex-col flex-1 min-w-0">
      <div
        v-if="chat.error"
        class="flex items-center gap-3 px-4 py-3 bg-red-50 border-b border-red-200 text-red-800 text-sm"
        role="alert"
      >
        <span class="flex-1">{{ chat.error }}</span>
        <button
          class="shrink-0 text-red-500 hover:text-red-700"
          aria-label="Dismiss"
          @click="chat.clearError()"
        >✕</button>
      </div>
      <MessageList
        :messages="chat.messages"
        :is-sending="chat.isSending || chat.isLoadingMessages"
      />
      <MessageInput
        :disabled="chat.isSending"
        :is-new-conversation="!chat.activeConversationId"
        @send="handleSend"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useModelsStore } from '@/stores/models'
import ConversationSidebar from '@/components/ConversationSidebar.vue'
import MessageList from '@/components/MessageList.vue'
import MessageInput from '@/components/MessageInput.vue'

const auth = useAuthStore()
const chat = useChatStore()
const models = useModelsStore()

const SIDEBAR_MIN = 160
const SIDEBAR_MAX = 480
const SIDEBAR_DEFAULT = 256

const sidebarWidth = ref(parseInt(localStorage.getItem('sidebarWidth') ?? '') || SIDEBAR_DEFAULT)
const isDragging = ref(false)

function onDrag(e: MouseEvent) {
  sidebarWidth.value = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, e.clientX))
  localStorage.setItem('sidebarWidth', String(sidebarWidth.value))
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}

function startDrag() {
  isDragging.value = true
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

function handleSend(message: string, modelId?: string): void {
  const model = models.getById(modelId)
  chat.sendMessage(message, modelId, model?.inputPricePer1k, model?.outputPricePer1k)
}

onUnmounted(stopDrag)

onMounted(() => {
  chat.fetchConversations()
  models.fetchModels()
})
</script>

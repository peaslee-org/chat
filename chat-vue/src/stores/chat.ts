import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { apiClient } from '@/lib/axios'
import type { Conversation, Message, ChatResponse, ApiMessage } from '@/types'

function extractError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversationId = ref<string | null>(null)
  const isLoading = ref(false)
  const isSending = ref(false)
  const isLoadingMessages = ref(false)
  const error = ref<string | null>(null)

  const activeConversation = computed(() =>
    conversations.value.find((c) => c.id === activeConversationId.value) ?? null,
  )

  const messages = computed<Message[]>(() => activeConversation.value?.messages ?? [])

  async function fetchConversations(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const { data } = await apiClient.get<Omit<Conversation, 'messages'>[]>(
        '/api/v1/conversations',
      )
      // Merge: preserve already-loaded messages for conversations already in the store
      const existing = new Map(conversations.value.map((c) => [c.id, c]))
      conversations.value = data.map((c) => ({
        ...c,
        messages: existing.get(c.id)?.messages ?? [],
      }))
    } catch (err) {
      error.value = extractError(err, 'Failed to load conversations')
    } finally {
      isLoading.value = false
    }
  }

  async function selectConversation(id: string): Promise<void> {
    activeConversationId.value = id
    const conv = conversations.value.find((c) => c.id === id)
    if (!conv) return
    conv.messages = []
    isLoadingMessages.value = true
    try {
      const { data } = await apiClient.get<ApiMessage[]>(`/api/v1/conversations/${id}/messages`)
      conv.messages = data.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: new Date(m.created_at),
      }))
    } catch {
      // silently fail — empty state is acceptable
    } finally {
      isLoadingMessages.value = false
    }
  }

  function startNewConversation(): void {
    activeConversationId.value = null
  }

  async function sendMessage(
    content: string,
    modelId?: string,
    inputPricePer1k?: number | null,
    outputPricePer1k?: number | null,
  ): Promise<void> {
    if (!content.trim()) return
    isSending.value = true
    error.value = null

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    }

    const existingConv = conversations.value.find((c) => c.id === activeConversationId.value)
    if (existingConv) {
      existingConv.messages.push(userMessage)
    } else {
      // Optimistically insert a temporary conversation so the user message renders immediately
      const tempId = `pending-${crypto.randomUUID()}`
      const now = new Date().toISOString()
      conversations.value.unshift({
        id: tempId,
        title: content.slice(0, 60),
        model_id: modelId ?? null,
        input_price_per_1k_tokens: inputPricePer1k ?? null,
        output_price_per_1k_tokens: outputPricePer1k ?? null,
        created_at: now,
        updated_at: now,
        messages: [userMessage],
      })
      activeConversationId.value = tempId
    }

    try {
      const payload = existingConv
        ? { conversation_id: existingConv.id, message: content }
        : { message: content, model_id: modelId, input_price_per_1k_tokens: inputPricePer1k, output_price_per_1k_tokens: outputPricePer1k }

      const { data } = await apiClient.post<ChatResponse>('/api/v1/chat', payload)

      if (!existingConv) {
        // Replace the temp conversation with the real one from the server
        const tempConv = conversations.value.find((c) => c.id === activeConversationId.value)
        const bufferedMessages = tempConv?.messages ?? [userMessage]
        await fetchConversations()
        const newConv = conversations.value.find((c) => c.id === data.conversation_id)
        if (newConv) newConv.messages = bufferedMessages
        activeConversationId.value = data.conversation_id
      }

      const conv = conversations.value.find((c) => c.id === activeConversationId.value)
      conv?.messages.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.reply,
        timestamp: new Date(),
      })
    } catch (err) {
      error.value = extractError(err, 'Failed to send message')
      const conv = conversations.value.find((c) => c.id === activeConversationId.value)
      if (existingConv) {
        conv?.messages.pop()
      } else {
        // Remove the temporary conversation on failure
        conversations.value = conversations.value.filter((c) => c.id !== activeConversationId.value)
        activeConversationId.value = null
      }
    } finally {
      isSending.value = false
    }
  }

  async function deleteConversation(id: string): Promise<void> {
    try {
      await apiClient.delete(`/api/v1/conversations/${id}`)
    } catch (err) {
      error.value = extractError(err, 'Failed to delete conversation')
      return
    }
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      startNewConversation()
    }
  }

  function clearError(): void {
    error.value = null
  }

  async function setConversationVisibility(id: string, isPublic: boolean): Promise<void> {
    const { data } = await apiClient.patch(`/api/v1/conversations/${id}`, { is_public: isPublic })
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) conv.is_public = data.is_public
  }

  return {
    conversations,
    activeConversationId,
    messages,
    isLoading,
    isSending,
    isLoadingMessages,
    error,
    fetchConversations,
    selectConversation,
    startNewConversation,
    sendMessage,
    deleteConversation,
    clearError,
    setConversationVisibility,
  }
})

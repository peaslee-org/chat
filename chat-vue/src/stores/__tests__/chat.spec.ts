import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/axios", () => ({ apiClient: { patch: vi.fn(), get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))

import { apiClient } from "@/lib/axios"
import { useChatStore } from "@/stores/chat"
import type { Conversation } from "@/types"

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "c1",
    title: "Hello",
    model_id: null,
    input_price_per_1k_tokens: null,
    output_price_per_1k_tokens: null,
    created_at: "2026-08-29T10:00:00Z",
    updated_at: "2026-08-29T10:00:00Z",
    messages: [],
    is_public: false,
    ...overrides,
  }
}

describe("chat store — visibility", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiClient.patch).mockReset()
  })

  it("setConversationVisibility PATCHes the conversation and flips is_public", async () => {
    const store = useChatStore()
    store.conversations.push(conversation())
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { is_public: true } })

    await store.setConversationVisibility("c1", true)

    expect(apiClient.patch).toHaveBeenCalledWith("/api/v1/conversations/c1", { is_public: true })
    expect(store.conversations.find((c) => c.id === "c1")?.is_public).toBe(true)
  })

  it("setConversationVisibility records the error and leaves is_public unchanged on failure", async () => {
    const store = useChatStore()
    store.conversations.push(conversation({ is_public: false }))
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("network down"))

    await store.setConversationVisibility("c1", true)

    expect(store.error).toBe("Failed to update visibility")
    expect(store.conversations.find((c) => c.id === "c1")?.is_public).toBe(false)
  })
})

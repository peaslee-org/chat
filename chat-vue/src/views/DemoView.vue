<script setup lang="ts">
import { onMounted, ref } from "vue"

import MeshViewer from "@/components/photogrammetry/MeshViewer.vue"
import MessageList from "@/components/MessageList.vue"
import TranscriptDisplay from "@/components/transcribe/TranscriptDisplay.vue"
import { DEFAULT_COMPILE_SETTINGS } from "@/composables/useMatchingThresholds"
import {
  getPublicConversation,
  getPublicScan,
  getPublicTranscription,
  getShowcase,
} from "@/lib/publicApi"
import { useAuthStore } from "@/stores/auth"
import type {
  Message,
  PublicScanDetail,
  PublicTranscriptionDetail,
  ShowcaseResponse,
} from "@/types"

const auth = useAuthStore()
const showcase = ref<ShowcaseResponse | null>(null)
const loadError = ref(false)
const scan = ref<PublicScanDetail | null>(null)
const scanPending = ref(false)
const scanError = ref(false)
const transcript = ref<PublicTranscriptionDetail | null>(null)
const transcriptionError = ref(false)
const messages = ref<Message[] | null>(null)
const activeConversationId = ref<string | null>(null)
const conversationError = ref(false)

onMounted(async () => {
  try {
    showcase.value = await getShowcase()
    const first = showcase.value.scans.find((s) => s.status === "complete")
    if (first) await openScan(first.job_id)
  } catch {
    loadError.value = true
  }
})

async function openScan(jobId: string) {
  scanPending.value = true
  try {
    scan.value = await getPublicScan(jobId)
    scanError.value = false
  } catch {
    scanError.value = true
  } finally {
    scanPending.value = false
  }
}

async function openTranscription(jobId: string) {
  try {
    transcript.value = await getPublicTranscription(jobId)
    transcriptionError.value = false
  } catch {
    transcriptionError.value = true
  }
}

async function openConversation(id: string) {
  activeConversationId.value = id
  try {
    const detail = await getPublicConversation(id)
    messages.value = detail.messages.map((m, i) => ({
      id: `${id}-${i}`,
      role: m.role,
      content: m.content,
      timestamp: new Date(m.created_at),
    }))
    conversationError.value = false
  } catch {
    conversationError.value = true
  }
}

function durationLabel(seconds: number | null): string {
  if (!seconds) return ""
  const m = Math.floor(seconds / 60)
  return `${m}m${Math.round(seconds % 60)}s`
}

function transcriptionChipLabel(t: { created_at: string; duration_seconds: number | null }): string {
  return [new Date(t.created_at).toLocaleDateString(), durationLabel(t.duration_seconds)]
    .filter(Boolean)
    .join(" · ")
}
</script>

<template>
  <div class="min-h-screen overflow-y-auto bg-gray-50 text-gray-900">
    <header class="border-b border-gray-200 bg-white px-6 py-4">
      <div class="mx-auto flex max-w-5xl items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold">aiTools</h1>
          <p class="text-sm text-gray-500">chat · transcribe · photogrammetry — a live demo of real results</p>
        </div>
        <RouterLink
          v-if="auth.isAuthenticated"
          to="/"
          class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >Open the app</RouterLink>
        <button
          v-else
          type="button"
          class="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
          data-testid="sign-in"
          @click="auth.login()"
        >Sign in</button>
      </div>
    </header>

    <main class="mx-auto max-w-5xl space-y-10 px-6 py-8">
      <p v-if="loadError" class="text-sm text-red-600" data-testid="demo-error">
        The demo backend is unreachable right now.
      </p>

      <section v-if="showcase?.scans.length" data-testid="section-scans">
        <h2 class="mb-1 text-lg font-semibold">Photogrammetry</h2>
        <p class="mb-3 text-sm text-gray-500">
          Photos in, textured 3D mesh out — COLMAP + OpenMVS on a spot GPU. Drag to orbit.
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="s in showcase.scans"
            :key="s.job_id"
            type="button"
            class="rounded border px-2.5 py-1 text-xs font-medium"
            :class="scan?.job_id === s.job_id ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'"
            data-testid="scan-chip"
            @click="openScan(s.job_id)"
          >{{ s.name }} · {{ s.image_count }} photos</button>
        </div>
        <div class="h-96 overflow-hidden rounded border border-gray-200 bg-white">
          <MeshViewer
            :src="scan?.mesh_url ?? null"
            :poster="scan?.preview_url ?? null"
            :mock="false"
            :pending="scanPending"
          />
        </div>
        <p v-if="scan?.matched != null" class="mt-2 text-xs text-gray-500">
          {{ scan.matched }} of {{ scan.total }} photos matched by structure-from-motion
        </p>
        <p v-if="scanError" class="mt-2 text-xs text-red-600" data-testid="section-error">
          This item is no longer available.
        </p>
      </section>

      <section v-if="showcase?.transcriptions.length" data-testid="section-transcriptions">
        <h2 class="mb-1 text-lg font-semibold">Transcription</h2>
        <p class="mb-3 text-sm text-gray-500">
          Speaker diarization (pyannote) + voice matching against enrolled speaker profiles.
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="t in showcase.transcriptions"
            :key="t.job_id"
            type="button"
            class="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
            data-testid="transcription-chip"
            @click="openTranscription(t.job_id)"
          >{{ transcriptionChipLabel(t) }}</button>
        </div>
        <div v-if="transcript" class="rounded border border-gray-200 bg-white p-4">
          <TranscriptDisplay :transcript="{ segments: transcript.segments, turns: null, settings: DEFAULT_COMPILE_SETTINGS, compiled_at: null }" />
        </div>
        <p v-if="transcriptionError" class="mt-2 text-xs text-red-600" data-testid="section-error">
          This item is no longer available.
        </p>
      </section>

      <section v-if="showcase?.conversations.length" data-testid="section-conversations">
        <h2 class="mb-1 text-lg font-semibold">Chat</h2>
        <p class="mb-3 text-sm text-gray-500">Claude via AWS Bedrock, per-conversation model choice.</p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="c in showcase.conversations"
            :key="c.conversation_id"
            type="button"
            class="rounded border px-2.5 py-1 text-xs font-medium"
            :class="activeConversationId === c.conversation_id ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'"
            data-testid="conversation-chip"
            @click="openConversation(c.conversation_id)"
          >{{ c.title ?? "Untitled" }}</button>
        </div>
        <div v-if="messages" class="rounded border border-gray-200 bg-white">
          <MessageList :messages="messages" :is-sending="false" />
        </div>
        <p v-if="conversationError" class="mt-2 text-xs text-red-600" data-testid="section-error">
          This item is no longer available.
        </p>
      </section>
    </main>
  </div>
</template>

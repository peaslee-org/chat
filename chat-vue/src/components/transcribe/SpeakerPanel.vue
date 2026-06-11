<script setup lang="ts">
import { ref } from "vue"
import { useTranscribeStore } from "@/stores/transcribe"
import SpeakerProfileCard from "./SpeakerProfileCard.vue"

const store = useTranscribeStore()
const newSpeakerName = ref("")
const isCreating = ref(false)

async function handleCreate() {
  const name = newSpeakerName.value.trim()
  if (!name) return
  isCreating.value = true
  try {
    await store.createSpeaker(name)
    newSpeakerName.value = ""
  } finally {
    isCreating.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-full bg-white p-4">
    <h2 class="text-sm font-semibold text-gray-700 mb-3">Speakers</h2>

    <!-- New speaker form -->
    <form class="flex gap-2 mb-4" @submit.prevent="handleCreate">
      <input
        v-model="newSpeakerName"
        type="text"
        placeholder="Speaker name"
        class="flex-1 text-sm border border-gray-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />
      <button
        type="submit"
        :disabled="!newSpeakerName.trim() || isCreating"
        class="text-sm px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        + Add
      </button>
    </form>

    <!-- Loading skeleton -->
    <div v-if="store.speakers.length === 0 && false" class="space-y-2">
      <div v-for="i in 3" :key="i" class="h-10 bg-gray-200 rounded animate-pulse" />
    </div>

    <!-- Empty state -->
    <div v-if="store.speakers.length === 0" class="text-center py-8 text-sm text-gray-500">
      <p>No speakers yet.</p>
      <p class="text-xs text-gray-400 mt-1">Add a speaker profile to enable named transcripts.</p>
    </div>

    <!-- Speaker list -->
    <div v-else class="flex-1 overflow-y-auto">
      <SpeakerProfileCard
        v-for="speaker in store.speakers"
        :key="speaker.speaker_id"
        :speaker="speaker"
      />
    </div>
  </div>
</template>

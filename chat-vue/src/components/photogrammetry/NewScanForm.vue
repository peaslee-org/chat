<script setup lang="ts">
import { computed, ref } from "vue"
import { usePhotogrammetryStore } from "@/stores/photogrammetry"
import ImageDropzone from "./ImageDropzone.vue"

const emit = defineEmits<{ submitted: [jobId: string] }>()

const store = usePhotogrammetryStore()

function defaultName(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `Scan ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const name = ref(defaultName())
const files = ref<File[]>([])
const submitting = ref(false)
const canSubmit = computed(() => files.value.length > 0 && !submitting.value)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const jobId = await store.submitScan(name.value.trim(), files.value)
    emit("submitted", jobId)
  } catch {
    // the store already raised a toast
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="mx-auto max-w-xl space-y-4" @submit.prevent="submit">
    <h2 class="text-base font-semibold">New scan</h2>
    <label class="block text-sm">
      <span class="text-gray-700">Name</span>
      <input v-model="name" type="text" maxlength="200" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
    </label>
    <ImageDropzone @files-changed="files = $event" />
    <div class="flex items-center gap-3">
      <button
        type="submit"
        class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        :disabled="!canSubmit"
      >{{ submitting ? "Uploading…" : "Start scan" }}</button>
      <span v-if="store.uploadProgress" class="text-sm text-gray-600">
        Uploading {{ store.uploadProgress.done }}/{{ store.uploadProgress.total }}
      </span>
    </div>
  </form>
</template>

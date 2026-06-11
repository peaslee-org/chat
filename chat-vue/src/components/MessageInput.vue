<template>
  <div class="border-t border-gray-200 bg-white p-4">
    <div v-if="isNewConversation" class="flex items-center gap-2 mb-3 text-sm text-gray-600">
      <label for="model-select" class="shrink-0 font-medium">Model:</label>
      <select
        id="model-select"
        v-model="selectedModelId"
        class="rounded-lg border border-gray-300 px-3 py-1.5 text-sm
               focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
      >
        <option v-for="model in modelsStore.models" :key="model.id" :value="model.id">
          {{ model.label }}{{ modelPriceLabel(model) }}
        </option>
      </select>
    </div>
    <form class="flex gap-3 items-end" @submit.prevent="handleSubmit">
      <textarea
        v-model="text"
        :disabled="disabled"
        rows="1"
        placeholder="Message..."
        class="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-3 text-sm
               focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50
               max-h-40 overflow-y-auto"
        @keydown.enter.exact.prevent="handleSubmit"
      />
      <button
        type="submit"
        :disabled="disabled || !text.trim()"
        class="shrink-0 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
               text-white rounded-xl px-5 py-3 text-sm font-medium transition-colors"
      >
        Send
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useModelsStore } from '@/stores/models'
import type { ModelOption } from '@/config/models'

defineProps<{ disabled: boolean; isNewConversation: boolean }>()

const emit = defineEmits<{
  send: [message: string, modelId?: string]
}>()

const modelsStore = useModelsStore()
const text = ref('')
const selectedModelId = ref(modelsStore.defaultModelId)

watch(
  () => modelsStore.defaultModelId,
  (id) => { selectedModelId.value = id },
)

function fmt(price: number): string {
  return price % 1 === 0 ? price.toFixed(0) : price.toFixed(2).replace(/\.?0+$/, '')
}

function modelPriceLabel(model: ModelOption): string {
  if (model.inputPricePer1k === null) return ''
  const inp = model.inputPricePer1k * 1000
  const out = model.outputPricePer1k !== null ? `/$${fmt(model.outputPricePer1k * 1000)}` : ''
  return ` — $${fmt(inp)}${out} per 1M`
}

function handleSubmit(): void {
  const trimmed = text.value.trim()
  if (!trimmed) return
  emit('send', trimmed, selectedModelId.value)
  text.value = ''
}
</script>

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiClient } from '@/lib/axios'
import type { Model } from '@/types'
import { AVAILABLE_MODELS, DEFAULT_MODEL_ID, type ModelOption } from '@/config/models'

export const useModelsStore = defineStore('models', () => {
  const models = ref<ModelOption[]>(AVAILABLE_MODELS)

  async function fetchModels(): Promise<void> {
    try {
      const { data } = await apiClient.get<Model[]>('/api/v1/models')
      if (data.length > 0) {
        models.value = data.map((m) => ({
          id: m.model_id,
          label: m.model_name,
          inputPricePer1k: m.input_price_per_1k_tokens,
          outputPricePer1k: m.output_price_per_1k_tokens,
        }))
      }
    } catch {
      // keep static fallback
    }
  }

  const defaultModelId = computed(() => models.value[0]?.id ?? DEFAULT_MODEL_ID)

  function getById(id: string | undefined): ModelOption | undefined {
    if (!id) return undefined
    return models.value.find((m) => m.id === id)
  }

  return { models, fetchModels, defaultModelId, getById }
})

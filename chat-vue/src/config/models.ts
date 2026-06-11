export interface ModelOption {
  id: string
  label: string
  inputPricePer1k: number | null
  outputPricePer1k: number | null
}

export const AVAILABLE_MODELS: ModelOption[] = [
  { id: 'anthropic.claude-3-5-sonnet-20241022-v2:0', label: 'Claude 3.5 Sonnet', inputPricePer1k: null, outputPricePer1k: null },
  { id: 'anthropic.claude-3-sonnet-20240229-v1:0', label: 'Claude 3 Sonnet', inputPricePer1k: null, outputPricePer1k: null },
  { id: 'anthropic.claude-3-5-haiku-20241022-v1:0', label: 'Claude 3.5 Haiku', inputPricePer1k: null, outputPricePer1k: null },
  { id: 'anthropic.claude-3-haiku-20240307-v1:0', label: 'Claude 3 Haiku', inputPricePer1k: null, outputPricePer1k: null },
  { id: 'anthropic.claude-3-opus-20240229-v1:0', label: 'Claude 3 Opus', inputPricePer1k: null, outputPricePer1k: null },
]

export const DEFAULT_MODEL_ID = AVAILABLE_MODELS[0].id

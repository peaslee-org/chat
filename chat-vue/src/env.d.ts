/// <reference types="vite/client" />

declare module 'virtual:mock-traffic' {
  import type { TrafficEntry } from './lib/trafficRecorder'
  const traffic: TrafficEntry[]
  export default traffic
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_COGNITO_DOMAIN: string
  readonly VITE_COGNITO_CLIENT_ID: string
  readonly VITE_COGNITO_REDIRECT_URI: string
  readonly VITE_COGNITO_SCOPE: string
  readonly VITE_MOCK_API?: string
  readonly VITE_POLL_INTERVAL_MS?: string
  readonly VITE_POLL_INTERVAL_PAUSED_MS?: string
  readonly VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

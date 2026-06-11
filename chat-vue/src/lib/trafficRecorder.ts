import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios'

const STORAGE_KEY = '__trafficLog'
const MAX_ENTRIES = 500

export interface TrafficEntry {
  method: string
  path: string
  params: Record<string, unknown>
  requestBody: unknown
  status: number
  responseData: unknown
}

interface PendingRequest {
  method: string
  path: string
  params: Record<string, unknown>
  requestBody: unknown
}

// Keyed by request id to correlate request/response interceptors
const pending = new Map<string, PendingRequest>()
let reqIdCounter = 0

function normalizePath(url: string): string {
  try {
    // If it's an absolute URL, extract just the pathname+search as path
    const u = new URL(url)
    return u.pathname
  } catch {
    // Already a relative path — strip query string
    return url.split('?')[0]
  }
}

function getLog(): TrafficEntry[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveLog(log: TrafficEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(log.slice(-MAX_ENTRIES)))
  } catch {
    // localStorage full — prune harder
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(log.slice(-50)))
    } catch {
      /* give up */
    }
  }
}

function appendEntry(entry: TrafficEntry): void {
  const log = getLog()
  log.push(entry)
  saveLog(log)
}

let attached = false

export function attachRecorder(client: AxiosInstance): void {
  if (attached) return
  attached = true

  client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const id = String(++reqIdCounter)
    ;(config as InternalAxiosRequestConfig & { __reqId?: string }).__reqId = id

    pending.set(id, {
      method: (config.method ?? 'get').toUpperCase(),
      path: normalizePath(config.url ?? ''),
      params: config.params ?? {},
      requestBody: config.data ?? null,
    })

    return config
  })

  client.interceptors.response.use(
    (response) => {
      const id = (response.config as InternalAxiosRequestConfig & { __reqId?: string }).__reqId
      if (id) {
        const req = pending.get(id)
        if (req) {
          appendEntry({ ...req, status: response.status, responseData: response.data })
          pending.delete(id)
        }
      }
      return response
    },
    (error: unknown) => {
      if (
        error != null &&
        typeof error === 'object' &&
        'config' in error &&
        'response' in error
      ) {
        const e = error as { config: InternalAxiosRequestConfig & { __reqId?: string }; response?: { status: number; data: unknown } }
        const id = e.config.__reqId
        if (id) {
          const req = pending.get(id)
          if (req && e.response) {
            appendEntry({ ...req, status: e.response.status, responseData: e.response.data })
          }
          pending.delete(id)
        }
      }
      return Promise.reject(error)
    },
  )
}

// Console helpers exposed on window.__traffic
export function exportTraffic(): void {
  const log = getLog()
  const blob = new Blob([JSON.stringify(log, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'traffic.json'
  a.click()
  URL.revokeObjectURL(url)
  console.info(`[traffic] Exported ${log.length} entries`)
}

export function clearTraffic(): void {
  localStorage.removeItem(STORAGE_KEY)
  console.info('[traffic] Cleared')
}

export function countTraffic(): number {
  return getLog().length
}

export function installConsoleHelpers(): void {
  Object.defineProperty(window, '__traffic', {
    value: {
      export: exportTraffic,
      clear: clearTraffic,
      count: () => {
        const n = countTraffic()
        console.info(`[traffic] ${n} entries captured`)
        return n
      },
    },
    writable: false,
  })
  console.info('[traffic] Recording active. Use window.__traffic.export() to download, window.__traffic.clear() to reset, window.__traffic.count() to check.')
}

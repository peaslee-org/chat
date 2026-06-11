import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { attachRecorder, installConsoleHelpers } from '@/lib/trafficRecorder'

export const apiClient = axios.create({
  headers: { 'Content-Type': 'application/json' },
})

// Activate traffic recording via browser console:
//   localStorage.setItem('__recordTraffic', 'true') then reload
//   window.__traffic.export()  — download traffic.json
//   window.__traffic.clear()   — reset captured entries
//   window.__traffic.count()   — how many entries so far
if (localStorage.getItem('__recordTraffic') === 'true') {
  attachRecorder(apiClient)
  installConsoleHelpers()
}

apiClient.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401
    ) {
      const auth = useAuthStore()
      auth.logout()
    }
    return Promise.reject(error)
  }
)

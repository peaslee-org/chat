import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiClient } from '@/lib/axios'

interface UserProfile {
  sub: string
  email?: string
  name?: string
}

export const useProfileStore = defineStore('profile', () => {
  const profile = ref<UserProfile | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchProfile(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const { data } = await apiClient.get<UserProfile>('/api/v1/profile')
      profile.value = data
    } catch {
      error.value = 'Failed to load profile.'
    } finally {
      loading.value = false
    }
  }

  return { profile, loading, error, fetchProfile }
})

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiClient } from '@/lib/axios'

interface AdminUser {
  sub: string
  email?: string
}

export const useAdminStore = defineStore('admin', () => {
  const users = ref<AdminUser[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchUsers(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const { data } = await apiClient.get<{ users: AdminUser[] }>('/api/v1/admin/users')
      users.value = data.users
    } catch {
      error.value = 'Failed to load users.'
    } finally {
      loading.value = false
    }
  }

  return { users, loading, error, fetchUsers }
})

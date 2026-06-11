<template>
  <div>
    <h1 class="text-2xl font-bold text-gray-900 mb-6">Users</h1>
    <p v-if="adminStore.loading" class="text-gray-500">Loading…</p>
    <p v-else-if="adminStore.error" class="text-red-600">{{ adminStore.error }}</p>
    <ul v-else class="divide-y divide-gray-200 bg-white rounded-lg shadow">
      <li v-for="user in adminStore.users" :key="user.sub" class="px-4 py-3 text-sm text-gray-800">
        {{ user.email ?? user.sub }}
      </li>
      <li v-if="adminStore.users.length === 0" class="px-4 py-3 text-sm text-gray-400">No users found.</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAdminStore } from '@/stores/admin'

const adminStore = useAdminStore()

onMounted(() => {
  adminStore.fetchUsers()
})
</script>

<template>
  <div class="max-w-lg mx-auto py-10 px-4">
    <h1 class="text-2xl font-bold text-gray-900 mb-6">Profile</h1>
    <p v-if="profileStore.loading" class="text-gray-500">Loading…</p>
    <div v-else-if="profileStore.profile" class="bg-white rounded-lg shadow p-6 space-y-3">
      <div>
        <span class="text-sm font-medium text-gray-500">Name</span>
        <p class="text-gray-900">{{ profileStore.profile.name ?? '—' }}</p>
      </div>
      <div>
        <span class="text-sm font-medium text-gray-500">Email</span>
        <p class="text-gray-900">{{ profileStore.profile.email ?? '—' }}</p>
      </div>
      <div>
        <span class="text-sm font-medium text-gray-500">User ID</span>
        <p class="font-mono text-xs text-gray-600">{{ profileStore.profile.sub }}</p>
      </div>
    </div>
    <p v-else-if="profileStore.error" class="text-red-600">{{ profileStore.error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useProfileStore } from '@/stores/profile'

const profileStore = useProfileStore()

onMounted(() => {
  profileStore.fetchProfile()
})
</script>

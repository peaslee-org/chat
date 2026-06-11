<template>
  <div class="flex h-screen items-center justify-center">
    <div v-if="error" class="text-red-600 text-sm">
      Authentication failed: {{ error }}
    </div>
    <div v-else class="text-gray-500 text-sm">Signing in...</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const error = ref<string | null>(null)

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')

  if (!code) {
    error.value = 'No authorization code received'
    return
  }

  try {
    await auth.handleCallback(code)
    await router.replace({ name: 'chat' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Unknown error'
  }
})
</script>

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { cognitoConfig } from '@/config/cognito'
import { generateCodeVerifier, generateCodeChallenge } from '@/lib/pkce'

// Local-dev auth bypass: pairs with chat-api's DEV_AUTH_BYPASS (which accepts requests with no
// Authorization header as sub `dev-auth-user-sub`). Only honoured in a Vite dev build — a
// production bundle ignores the variable entirely.
export const devAuthBypass =
  import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH_BYPASS === 'true'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('id_token'))

  const isAuthenticated = computed(() => devAuthBypass || token.value !== null)

  const isAdmin = computed<boolean>(() => {
    if (!token.value) return false
    try {
      const payload = token.value.split('.')[1]
      const claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
      const groups: string[] = claims['cognito:groups'] ?? []
      return groups.includes('admin')
    } catch {
      return false
    }
  })

  async function login(): Promise<void> {
    if (devAuthBypass) return
    const verifier = await generateCodeVerifier()
    const challenge = await generateCodeChallenge(verifier)
    sessionStorage.setItem('pkce_verifier', verifier)

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: cognitoConfig.clientId,
      redirect_uri: cognitoConfig.redirectUri,
      scope: cognitoConfig.scope,
      code_challenge: challenge,
      code_challenge_method: 'S256',
    })
    window.location.href = `${cognitoConfig.authorizeUrl}?${params.toString()}`
  }

  async function handleCallback(code: string): Promise<void> {
    const verifier = sessionStorage.getItem('pkce_verifier')
    if (!verifier) throw new Error('Missing PKCE verifier')

    const params = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: cognitoConfig.clientId,
      redirect_uri: cognitoConfig.redirectUri,
      code,
      code_verifier: verifier,
    })

    const response = await axios.post<{ id_token: string }>(
      cognitoConfig.tokenUrl,
      params.toString(),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    )

    sessionStorage.removeItem('pkce_verifier')
    token.value = response.data.id_token
    localStorage.setItem('id_token', response.data.id_token)
  }

  function logout(): void {
    token.value = null
    localStorage.removeItem('id_token')
    if (devAuthBypass) {
      window.location.href = '/'
      return
    }
    window.location.href = cognitoConfig.logoutUrl
  }

  return { token, isAuthenticated, isAdmin, login, handleCallback, logout }
})

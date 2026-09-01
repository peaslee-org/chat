import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { authGuard } from "../index"
import { useAuthStore } from "@/stores/auth"

function to(meta: Record<string, unknown>) {
  return { meta } as never
}

// isAdmin decodes the JWT payload (stores/auth.ts:18-28), so the token must be well-formed
function makeToken(groups: string[] = []): string {
  return `h.${btoa(JSON.stringify({ "cognito:groups": groups }))}.s`
}

describe("authGuard", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it("sends logged-out visitors to the demo instead of Cognito", () => {
    expect(authGuard(to({ requiresAuth: true }))).toEqual({ name: "demo" })
  })

  it("lets logged-out visitors reach unguarded routes", () => {
    expect(authGuard(to({}))).toBeUndefined()
  })

  it("passes authenticated users through", () => {
    const auth = useAuthStore()
    auth.token = makeToken()
    expect(authGuard(to({ requiresAuth: true }))).toBeUndefined()
  })

  it("bounces non-admins off admin routes", () => {
    const auth = useAuthStore()
    auth.token = makeToken()
    expect(authGuard(to({ requiresAuth: true, requiresAdmin: true }))).toEqual({ name: "chat" })
  })
})

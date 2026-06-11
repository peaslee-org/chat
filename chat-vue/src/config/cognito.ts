export const cognitoConfig = {
  domain: import.meta.env.VITE_COGNITO_DOMAIN,
  clientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
  redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI,
  scope: import.meta.env.VITE_COGNITO_SCOPE,

  get tokenUrl(): string {
    return `https://${this.domain}/oauth2/token`
  },

  get authorizeUrl(): string {
    return `https://${this.domain}/oauth2/authorize`
  },

  get logoutUrl(): string {
    const appRoot = this.redirectUri.replace('/callback', '')
    return (
      `https://${this.domain}/logout` +
      `?client_id=${this.clientId}` +
      `&logout_uri=${encodeURIComponent(appRoot)}`
    )
  },
}

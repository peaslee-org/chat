# ADR 003 — Cognito Auth: PKCE Flow, No Client Secret

**Date:** 2026-03-08
**Status:** Accepted

## Context

The chat-vue SPA needs to authenticate users against AWS Cognito and obtain tokens for API calls.

## Decision

Use **PKCE (Proof Key for Code Exchange)** OAuth2 flow with no client secret.

## Reason

- SPAs cannot safely store a client secret (JavaScript is visible to the browser)
- PKCE provides the same security guarantees as client credentials for public clients
- Cognito's Hosted UI supports PKCE natively
- The `id_token` (RS256 JWT) is sent as `Authorization: Bearer` to chat-api, which validates it against Cognito's JWKS URL

## Consequences

- Cognito App Client is configured as a **public client** (no client secret)
- Both production callback URL and `http://localhost:5173/callback` must be allowlisted in the App Client
- Backend validates JWTs using the Cognito JWKS endpoint; keys are cached in-process
- `CORS_ORIGINS` in chat-api must include both the CloudFront domain and `http://localhost:5173`

// Two ways into the portal (plan section 9):
// - sign in: OIDC against Keycloak (realm "bis", public client "bis-frontend", code + PKCE);
//   admins get their admin scopes through their role, Keycloak enforces their OTP.
// - guest: after a Cloudflare Turnstile check the API issues a short-lived read-only token.
// Configuration is public (no secrets); an empty VITE_OIDC_AUTHORITY disables login (local tools).
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

const authority = import.meta.env.VITE_OIDC_AUTHORITY ?? ''
export const authEnabled = authority !== ''

export type Session = 'user' | 'guest' | 'anonymous'

const GUEST_KEY = 'bis.guest'

const manager = authEnabled
  ? new UserManager({
      authority,
      client_id: import.meta.env.VITE_OIDC_CLIENT_ID ?? 'bis-frontend',
      redirect_uri: `${window.location.origin}/`,
      post_logout_redirect_uri: `${window.location.origin}/`,
      response_type: 'code',
      scope: 'openid profile read:kpi',
      // Session-scoped: closing the tab ends the session in this browser.
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      automaticSilentRenew: true,
    })
  : null

let current: User | null = null
manager?.events.addUserLoaded((user) => {
  current = user
})
manager?.events.addUserUnloaded(() => {
  current = null
})

interface GuestToken {
  token: string
  expiresAt: number
}

function readGuest(): GuestToken | null {
  try {
    const raw = window.sessionStorage.getItem(GUEST_KEY)
    const parsed = raw ? (JSON.parse(raw) as GuestToken) : null
    return parsed && parsed.expiresAt > Date.now() ? parsed : null
  } catch {
    return null
  }
}

function clearGuest(): void {
  try {
    window.sessionStorage.removeItem(GUEST_KEY)
  } catch {
    // storage unavailable: nothing to clear
  }
}

let session: Session = 'anonymous'

export function currentSession(): Session {
  return session
}

export function accessToken(): string | null {
  if (session === 'guest') return readGuest()?.token ?? null
  return current && !current.expired ? current.access_token : null
}

export function userName(): string | null {
  if (session === 'guest') return 'Gast'
  return current?.profile.preferred_username ?? current?.profile.name ?? null
}

/** Starts the login redirect; the current view (path + query) is restored afterwards. */
export function login(): Promise<void> {
  return manager ? manager.signinRedirect({ state: window.location.pathname + window.location.search }) : Promise.resolve()
}

/** Exchanges a Turnstile token for a guest token and switches to the guest session. */
export async function continueAsGuest(turnstileToken: string): Promise<void> {
  const response = await fetch('/api/v1/guest/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ turnstile_token: turnstileToken }),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(response.status === 429 ? 'Zu viele Gastzugänge, bitte später erneut versuchen.' : detail)
  }
  const guest: GuestToken = { token: body.access_token, expiresAt: Date.now() + (body.expires_in - 30) * 1000 }
  window.sessionStorage.setItem(GUEST_KEY, JSON.stringify(guest))
  session = 'guest'
}

export async function logout(): Promise<void> {
  if (session === 'guest') {
    clearGuest()
    window.location.assign('/')
    return
  }
  if (manager) await manager.signoutRedirect()
}

/** Called when the API answers 401: an expired guest goes back to the start page, a signed-in
 *  user logs in again and comes back to the same view. */
export function sessionExpired(): void {
  if (session === 'guest') {
    clearGuest()
    window.location.assign('/')
  } else if (manager) {
    void login()
  }
}

/** Decides what to render: a signed-in user, a guest, or the start page. */
export async function initAuth(): Promise<Session> {
  if (!manager) {
    session = 'user' // login disabled (local tools): everything is open
    return session
  }
  const params = new URLSearchParams(window.location.search)
  if (params.has('code') && params.has('state')) {
    current = await manager.signinRedirectCallback()
    const target = typeof current.state === 'string' && current.state.startsWith('/') ? current.state : '/'
    window.history.replaceState(null, '', target)
    session = 'user'
    return session
  }
  current = await manager.getUser()
  if (current && !current.expired) session = 'user'
  else if (readGuest()) session = 'guest'
  else session = 'anonymous'
  return session
}

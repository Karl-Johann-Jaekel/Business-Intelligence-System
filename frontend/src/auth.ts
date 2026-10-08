// OIDC login against Keycloak (realm "bis", public client "bis-frontend", authorization code + PKCE).
// Configuration is public (no secrets); an empty VITE_OIDC_AUTHORITY disables login.
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'

const authority = import.meta.env.VITE_OIDC_AUTHORITY ?? ''
export const authEnabled = authority !== ''

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

export function accessToken(): string | null {
  return current && !current.expired ? current.access_token : null
}

export function userName(): string | null {
  return current?.profile.preferred_username ?? current?.profile.name ?? null
}

/** Starts the login redirect; the current view (path + query) is restored afterwards. */
export function login(): Promise<void> {
  return manager ? manager.signinRedirect({ state: window.location.pathname + window.location.search }) : Promise.resolve()
}

export function logout(): Promise<void> {
  return manager ? manager.signoutRedirect() : Promise.resolve()
}

/** Resolves once the user is authenticated (or login is disabled). Returns false while the
 *  browser is being redirected to the login page. */
export async function initAuth(): Promise<boolean> {
  if (!manager) return true
  const params = new URLSearchParams(window.location.search)
  if (params.has('code') && params.has('state')) {
    current = await manager.signinRedirectCallback()
    const target = typeof current.state === 'string' && current.state.startsWith('/') ? current.state : '/'
    window.history.replaceState(null, '', target)
    return true
  }
  current = await manager.getUser()
  if (current && !current.expired) return true
  await login()
  return false
}

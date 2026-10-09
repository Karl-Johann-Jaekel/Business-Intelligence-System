import { useCallback, useState } from 'react'
import App from '../App'
import type { Session } from '../auth'
import { Landing } from './Landing'

/** Signed-in users and guests see the portal, everyone else the start page. */
export function Root({ initial }: { initial: Session }) {
  const [session, setSession] = useState(initial)
  const onEntered = useCallback(() => setSession('guest'), [])
  return session === 'anonymous' ? <Landing onEntered={onEntered} /> : <App />
}

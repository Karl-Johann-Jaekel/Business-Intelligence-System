import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { initAuth } from './auth'
import { Root } from './components/Root'

const root = createRoot(document.getElementById('root')!)

initAuth()
  .then((session) =>
    root.render(
      <StrictMode>
        <Root initial={session} />
      </StrictMode>,
    ),
  )
  .catch((err: unknown) => {
    const p = document.createElement('p')
    p.className = 'error app'
    p.textContent = `Anmeldung fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`
    document.getElementById('root')!.replaceChildren(p)
  })

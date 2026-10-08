import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initAuth } from './auth'

const root = createRoot(document.getElementById('root')!)

// Render only once authenticated; otherwise the browser is on its way to the login page.
initAuth()
  .then((ready) => {
    if (ready)
      root.render(
        <StrictMode>
          <App />
        </StrictMode>,
      )
  })
  .catch((err: unknown) => {
    const p = document.createElement('p')
    p.className = 'error app'
    p.textContent = `Anmeldung fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`
    document.getElementById('root')!.replaceChildren(p)
  })

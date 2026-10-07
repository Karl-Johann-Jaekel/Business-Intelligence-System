import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs in docker compose on 127.0.0.1:8102 (BIS_API_PORT); the dev server proxies /api.
const apiTarget = process.env.BIS_API_URL ?? 'http://127.0.0.1:8102'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: { '/api': apiTarget },
  }
})

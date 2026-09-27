import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
    // Let a temporary Cloudflare tunnel reach the dev server, for testing on a phone
    // (`make tunnel`). The tuning page still refuses requests that come through it.
    allowedHosts: ['.trycloudflare.com'],
  },
})

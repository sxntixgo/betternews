import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Served under /app in production so the HTMX UI keeps / until parity (plan
// C.4). The dev server stays at the root, or every test URL would need the
// prefix. `command` is 'build' only for a production bundle.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/app/' : '/',
  plugins: [react()],
  resolve: {
    // The API contract is shared with the native app, so it lives outside web/.
    alias: { '@shared': path.resolve(__dirname, '../shared') },
  },
  server: {
    // Dev server talks to the Flask app, so the browser sees one origin and
    // there is no CORS to configure on the API.
    proxy: { '/api': { target: 'http://127.0.0.1:5001', changeOrigin: true } },
  },
}))

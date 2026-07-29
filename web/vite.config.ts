import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
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
})

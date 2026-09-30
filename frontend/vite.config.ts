import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// During local development the Vite server forwards API calls to the Docker Compose gateway.
// CAMPUS_DIRECT=1 instead proxies each API prefix straight to a locally running service (no gateway/nginx),
// used only for quick non-Docker smoke runs; the gateway path above remains the default for everyone else.
const direct = process.env.CAMPUS_DIRECT === '1'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: direct
      ? {
          '/api/v1/auth': { target: 'http://localhost:8001', changeOrigin: false },
          '/api/v1/platform': { target: 'http://localhost:8001', changeOrigin: false },
          '/api/v1/academic': { target: 'http://localhost:8002', changeOrigin: false },
          '/api/v1/finance': { target: 'http://localhost:8003', changeOrigin: false },
          '/api/v1/hr': { target: 'http://localhost:8004', changeOrigin: false },
        }
      : {
          '/api': { target: process.env.CAMPUS_GATEWAY ?? 'http://localhost:8080', changeOrigin: false },
        },
  },
  build: {
    chunkSizeWarningLimit: 700,
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// En desarrollo, /api va al backend FastAPI de main_frontend_react.py (puerto
// 8001). En producción ese mismo backend sirve dist/, así que no hace falta proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8001', changeOrigin: false } },
  },
})

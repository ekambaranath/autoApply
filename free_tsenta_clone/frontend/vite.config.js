import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The build lands in frontend/dist, which app/main.py mounts on the same origin
// as the API. In dev, `npm run dev` proxies /api to the local FastAPI server so
// the frontend code never needs to know which mode it is running in.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})

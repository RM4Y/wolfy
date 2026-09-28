import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev: `npm run dev` proxies the API to a backend on :8420
export default defineConfig({
  plugins: [vue()],
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://localhost:8420' } },
})

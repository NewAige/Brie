import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// All assets are bundled locally — no external CDNs, fonts, or scripts
// (spec §8.3). The build output is fully self-contained static files.
export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev outside docker: proxy API + auth to the backend.
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
})

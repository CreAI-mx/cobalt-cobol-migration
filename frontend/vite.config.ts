import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/migration': {
        target: 'http://localhost:8123',
        changeOrigin: true,
      },
    },
  },
})

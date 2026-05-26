import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// Sprint 5 PR-B — Tailwind v4 의 @tailwindcss/vite plugin 통합.
// Tauri shell 이 spawn 한 dev server (포트 5173) 가 strict 하므로 strictPort=true.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// Sprint 5 — Tauri 데스크탑 앱 통합.
//
// 2026-05-26 fix: `@tauri-apps/api/core` 와 `/event` 서브 경로를 optimizeDeps.include
// 에 명시. Vite 가 PR-D (#198) 머지 시점에 @tauri-apps/api 신규 dep 의 prebundle
// 을 cache miss 처리해 dev server 에서 `Failed to resolve module specifier
// '@tauri-apps/api/core'` 발생한 사례 fix. 또한 Tauri 가 spawn 한 dev server
// (`npm --prefix frontend run dev`) 에서 클린 cache 시작 시 robust.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      // src-tauri 변경은 cargo 가 별도 watch 하므로 Vite 가 중복 reload 안 하도록.
      ignored: ['**/src-tauri/**'],
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  optimizeDeps: {
    include: [
      '@tauri-apps/api/core',
      '@tauri-apps/api/event',
    ],
  },
})

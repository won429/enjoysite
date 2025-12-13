import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  base: "/enjoysite/",
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'map.html'), // 여기가 핵심! map.html을 메인으로 설정
      },
    },
  },
})
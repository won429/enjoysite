import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: "/enjoysite/",
  build: {
    rollupOptions: {
      input: {
        main: 'map.html',
      },
    },
  },
})

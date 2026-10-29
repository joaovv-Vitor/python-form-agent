import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',
  publicDir: '../extension/public',
  build: {
    outDir: '../extension/dist',
    emptyOutDir: true,
    rollupOptions: { input: ['extension.html', 'microphone.html'] },
  },
})

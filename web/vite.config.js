import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:3002'
    },
    fs: {
      allow: ['..']
    }
  },
  // Azure Speech SDK requires this Node built-in shimmed
  define: {
    global: 'globalThis'
  }
})

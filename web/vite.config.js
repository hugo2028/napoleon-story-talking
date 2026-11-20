import { defineConfig } from 'vite'

export default defineConfig({
  // Lit le .env à la racine du projet. Seules les variables VITE_* sont exposées au navigateur
  // (ex. VITE_DEMO_RECORDER) : les clés API restent côté serveur.
  envDir: '..',
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

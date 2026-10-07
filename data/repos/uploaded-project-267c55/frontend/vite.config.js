import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
  build: {
    // Split rarely-changing vendor code (react/react-dom/leaflet/uuid)
    // into its own chunk, separate from app code that changes on every
    // deploy — the browser can then keep caching the vendor chunk
    // across releases instead of re-downloading it every time. Paired
    // with the React.lazy()-based route splitting in App.jsx (each
    // admin/manager page becomes its own on-demand chunk), this is
    // what actually addresses the ">500kB" warning rather than just
    // raising the threshold to silence it.
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          leaflet: ['leaflet'],
        },
      },
    },
  },
  test: {
    // Vitest reuses this same Vite config (same JSX transform, same
    // resolve/alias setup) rather than needing a second, separately
    // maintained Jest config that could quietly drift out of sync with
    // how the app is actually built — this is the main practical
    // reason to pick Vitest over Jest for a Vite project specifically.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.js'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['node_modules/', 'src/setupTests.js'],
    },
  },
})

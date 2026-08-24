import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server proxies API calls to the FastAPI backend so the SPA can use
// relative `/api` URLs in development. In production the web app and API are
// served behind the same origin (or a gateway), or VITE_API_BASE_URL points at
// the API host directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
});

// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  integrations: [react()],
  server: {
    host: '0.0.0.0',
    port: 4321,
  },
  vite: {
    server: {
      proxy: {
        '/admin':   { target: `http://${process.env.DIRECTUS_HOST || 'localhost'}:8055`, rewrite: path => path.replace(/^\/admin/, '') },
        '/api':     { target: `http://${process.env.FETCHER_HOST  || 'localhost'}:8000`, rewrite: path => path.replace(/^\/api/, '') },
        '/whisper': { target: `http://${process.env.WHISPER_HOST  || 'localhost'}:8001`, rewrite: path => path.replace(/^\/whisper/, '') },
      },
    },
  },
});

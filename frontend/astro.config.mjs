// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  integrations: [react()],
  server: {
    host: '0.0.0.0',
    port: 4321,
    allowedHosts: true,
  },
  vite: {
    server: {
      proxy: {
        '/api': {
          target: `http://${process.env.FETCHER_HOST || 'localhost'}:8000`,
          rewrite: path => path.replace(/^\/api/, ''),
          headers: { 'X-App-Token': process.env.APP_API_TOKEN || '' },
        },
        '/whisper': {
          target: `http://${process.env.WHISPER_HOST || 'localhost'}:8001`,
          rewrite: path => path.replace(/^\/whisper/, ''),
          headers: { 'X-App-Token': process.env.APP_API_TOKEN || '' },
        },
      },
    },
  },
});

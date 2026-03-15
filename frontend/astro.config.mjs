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
    define: {
      'import.meta.env.PUBLIC_DIRECTUS_URL': JSON.stringify(process.env.PUBLIC_DIRECTUS_URL || 'http://localhost:8055'),
      'import.meta.env.PUBLIC_DIRECTUS_TOKEN': JSON.stringify(process.env.PUBLIC_DIRECTUS_TOKEN || 'admin-token-change-me'),
      'import.meta.env.PUBLIC_FETCHER_URL': JSON.stringify(process.env.PUBLIC_FETCHER_URL || 'http://localhost:8000'),
    },
  },
});

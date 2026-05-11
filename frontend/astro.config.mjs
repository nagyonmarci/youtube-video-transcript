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
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('/markmap-view/')) return 'markmap-view';
            if (id.includes('/markmap-lib/')) return 'markmap-lib';
            if (id.includes('/d3-')) return 'markmap-d3';
            if (id.includes('/katex/') || id.includes('/htmlparser2/') || id.includes('/domhandler/') || id.includes('/domutils/') || id.includes('/entities/')) {
              return 'markmap-render';
            }
            return undefined;
          },
        },
      },
    },
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

import { defineConfig } from 'vite';
import path from 'node:path';

// https://vitejs.dev/config
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
        downloadOverlay: path.resolve(__dirname, 'download-overlay.html'),
      },
    },
  },
});

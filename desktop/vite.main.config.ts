import { defineConfig } from 'vite';
import fs from 'node:fs';
import path from 'node:path';

const bundledNodePtyDir = path.resolve('.vite/build/node_modules/node-pty');

function copyNodePtyPlugin() {
  return {
    name: 'copy-node-pty',
    closeBundle() {
      // Forge's Vite plugin packages only .vite output. node-pty must remain
      // external to Rollup, so copy its runtime package into that output tree.
      fs.rmSync(bundledNodePtyDir, { recursive: true, force: true });
      fs.cpSync(path.resolve('node_modules/node-pty'), bundledNodePtyDir, {
        recursive: true,
      });
    },
  };
}

// https://vitejs.dev/config
export default defineConfig({
  plugins: [copyNodePtyPlugin()],
  // node-pty loads platform-specific .node binaries at runtime. Keeping it
  // external lets Electron Forge copy the package and AutoUnpackNativesPlugin
  // place those binaries outside app.asar where Node can load them.
  build: {
    rollupOptions: {
      external: ['node-pty'],
    },
  },
});

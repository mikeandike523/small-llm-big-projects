import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Load all env vars from ui/.env (no VITE_ prefix restriction here)
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [
      react({
        jsxImportSource: '@emotion/react',
      }),
    ],
    server: {
      port: parseInt(env.UI_PORT ?? '5173'),
    },
  }
})

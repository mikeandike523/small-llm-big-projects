import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

export default defineConfig(({ mode }) => {
  // Load all env vars from ui/.env (no VITE_ prefix restriction here)
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [
      react({
        jsxImportSource: "@emotion/react",
      }),
    ],
    // Bundle the UI's own version number (ui/package.json) as a build-time
    // constant so the frontend can display it without an API round-trip.
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
    },
    server: {
      port: parseInt(env.UI_PORT ?? "5173"),
    },
  };
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    allowedHosts: ["web", "localhost", "127.0.0.1"],
    proxy: {
      "/v1": "http://api:8000",
      "/docs": "http://api:8000",
      "/openapi.json": "http://api:8000"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**"],
    setupFiles: "./src/test/setup.ts"
  }
});

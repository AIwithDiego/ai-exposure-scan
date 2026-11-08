import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // GitHub Pages serves the demo from /ai-exposure-scan/; local builds stay at /.
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
  // The scan server only accepts POSTs from http://localhost:5173, so fail rather than drift to another port.
  server: { port: 5173, strictPort: true, proxy: { "/api": "http://localhost:8000" } },
});

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-only proxy: `npm run dev` forwards /api to the locally running backend.
// The production image does the same job with nginx (frontend/nginx.conf),
// so the SPA always talks to a same-origin /api and never needs CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});

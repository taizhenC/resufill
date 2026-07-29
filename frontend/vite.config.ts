import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// Builds straight into the Python package so the wheel ships the UI and FastAPI serves it
// from resume_fill/webui. No runtime CDN, ever: the whole tool is local, and a page that
// needs the network to render your own résumé would be a strange thing to have built.
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "../resume_fill/webui",
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    // `npm run dev` serves the client with hot reload and forwards the API to the Python
    // server started separately with `resume-fill serve --no-open`.
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});

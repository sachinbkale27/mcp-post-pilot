import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Uploaded images live at /media/... (served by CloudFront on AWS, by the blog API locally).
  server: { proxy: { "/media": "http://localhost:8100" } },
});

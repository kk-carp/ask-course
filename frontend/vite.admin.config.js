import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    emptyOutDir: false,
    lib: {
      entry: "src/admin/main.js",
      name: "ArborseekAdmin",
      formats: ["iife"],
      fileName: () => "admin.js",
      cssFileName: "admin",
    },
    sourcemap: true,
  },
});

import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()],
  define: {'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'production'), __VUE_OPTIONS_API__: true, __VUE_PROD_DEVTOOLS__: false, __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false},
  build: {lib: {entry: 'src/main.js', name: 'ArborseekWidget', formats: ['iife'], fileName: () => 'widget.js'}, sourcemap: true},
  server: {proxy: Object.fromEntries(['/ask', '/widget', '/purchase', '/health', '/me', '/auth', '/documents', '/courses'].map(path => [path, 'http://127.0.0.1:8000']))},
});

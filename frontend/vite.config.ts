/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { normalizeBase } from './src/utils/basePath'

export default defineConfig({
  // The site root by default. CI sets DOE_BASE_PATH (e.g. /k-on/) when the app is served from a sub-path.
  base: normalizeBase(process.env.DOE_BASE_PATH),
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  cacheDir: '.vite-cache',
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: process.env.DOE_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: {
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: { 'element-plus': ['element-plus'], echarts: ['echarts'], vue: ['vue', 'vue-router', 'pinia'] },
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.spec.ts'],
    css: false,
    server: { deps: { inline: ['element-plus'] } },
  },
})

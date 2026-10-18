/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
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

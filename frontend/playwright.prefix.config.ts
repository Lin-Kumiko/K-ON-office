import { defineConfig } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

// Same isolated backend as the main E2E suite, but the frontend is built for a sub-path
// (`vite build --base=/k-on/`) and the app is served under /k-on, the way nginx exposes it on the server.
// Run with `npm run e2e:prefix`; do not run it at the same time as `npm run e2e` (both reset tests/.e2e-data).
process.env.E2E_PASSWORD ||= `E2e${randomBytes(4).toString('hex')}7`
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')
const PORT = 8766
const PREFIX = '/k-on'
const DIST = path.join(root, 'frontend', 'dist-prefix')

export default defineConfig({
  testDir: './e2e-prefix',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: '../tests/e2e-results/artifacts-prefix',
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: 'chrome', // use the locally installed Google Chrome; no browser download
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  },
  webServer: {
    command: `"${python}" "${path.join(root, 'scripts', 'e2e_server.py')}" --port ${PORT} --prefix ${PREFIX} --dist "${DIST}"`,
    url: `http://127.0.0.1:${PORT}${PREFIX}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { E2E_PASSWORD: process.env.E2E_PASSWORD },
  },
})

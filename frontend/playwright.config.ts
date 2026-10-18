import { defineConfig } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

// Synthetic, per-run password for the isolated E2E database (never written to disk by us).
process.env.E2E_PASSWORD ||= `E2e${randomBytes(4).toString('hex')}7`
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')
const PORT = 8765

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: '../tests/e2e-results/artifacts',
  reporter: [['list'], ['json', { outputFile: '../tests/e2e-results/report.json' }]],
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
    command: `"${python}" "${path.join(root, 'scripts', 'e2e_server.py')}" --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { E2E_PASSWORD: process.env.E2E_PASSWORD },
  },
})

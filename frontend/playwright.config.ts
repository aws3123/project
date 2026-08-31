import { defineConfig } from '@playwright/test'

const useSystemChrome = process.env.PW_USE_SYSTEM_CHROME === '1'

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 1,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    ...(useSystemChrome ? { channel: 'chrome' as const } : {}),
  },
  webServer: {
    command: 'pnpm build && pnpm preview --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
})

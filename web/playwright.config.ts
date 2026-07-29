import { defineConfig, devices } from '@playwright/test';

/**
 * The API is mocked at the network layer (see e2e/fixtures.ts), so these tests
 * need no Flask, no database and no token. They exercise what the SPA itself is
 * responsible for -- layout, paging, state -- and stay fast and deterministic.
 *
 * Uses the installed Chrome rather than downloading a browser.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  reporter: process.env.CI ? 'dot' : 'list',
  use: { baseURL: 'http://localhost:5175', channel: 'chrome' },
  projects: [
    // The iPhone descriptor defaults to WebKit, which cannot use the Chrome
    // channel. Keep its metrics -- viewport, DPR, touch, isMobile -- and run
    // them on the Chrome that is already installed.
    {
      name: 'phone',
      use: { ...devices['iPhone 13'], browserName: 'chromium', channel: 'chrome' },
    },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
  ],
  webServer: {
    command: 'npx vite --port 5175 --strictPort',
    url: 'http://localhost:5175',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});

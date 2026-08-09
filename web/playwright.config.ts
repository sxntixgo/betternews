import { defineConfig, devices } from '@playwright/test';

/**
 * The API is mocked at the network layer (see e2e/fixtures.ts), so these tests
 * need no Flask, no database and no token. They exercise what the SPA itself is
 * responsible for -- layout, paging, state -- and stay fast and deterministic.
 *
 * Uses the installed Chrome rather than downloading a browser.
 */
// Locally, use the Chrome that is already installed rather than downloading a
// second browser. CI has no Chrome, so it installs Playwright's own chromium and
// leaves the channel unset -- one env var instead of two configs.
const channel = process.env.CI ? undefined : 'chrome';

export default defineConfig({
  testDir: './e2e',
  // The mocked projects must not pick up the live spec, and vice versa.
  testIgnore: process.env.BN_E2E_TOKEN ? [] : ['**/live.spec.ts'],
  fullyParallel: true,
  reporter: process.env.CI ? 'dot' : 'list',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // `channel` is NOT set here. A top-level `use` is inherited by every project
  // and cannot be un-set from one -- `channel: undefined` does not override it
  // -- and WebKit rejects a Chrome channel outright. So each Chromium project
  // opts in instead.
  use: { baseURL: 'http://localhost:5175' },
  projects: [
    // The iPhone descriptor defaults to WebKit, which cannot use the Chrome
    // channel. Keep its metrics -- viewport, DPR, touch, isMobile -- and run
    // them on the Chrome that is already installed.
    {
      name: 'phone',
      use: { ...devices['iPhone 13'], browserName: 'chromium', channel },
    },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], channel } },

    // Actual WebKit, and the reason it exists: `phone` above runs Chromium with
    // an iPhone's *metrics*, so for the whole life of this app the engine the
    // reader actually uses had never executed a line of it. The app then failed
    // to load on an iPhone while every phone test passed -- a suite cannot
    // catch an engine it does not run.
    //
    {
      name: 'safari',
      use: { ...devices['iPhone 13'] },
    },

    // The live suite. Everything else mocks the API at the network layer, which
    // means no committed test has ever crossed browser -> proxy -> Flask ->
    // Postgres. That gap is how a 302-to-/login on every API call survived a
    // suite of a thousand passing tests: the test client was already signed in,
    // so nothing anonymous ever spoke to the real app.
    {
      name: 'live',
      testMatch: /live\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], channel },
    },
  ],
  webServer: {
    command: 'npx vite --port 5175 --strictPort',
    url: 'http://localhost:5175',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});

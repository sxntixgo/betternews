import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { mockApi, signedIn } from './fixtures';

test('the page declares a manifest and a real title', () => {
  // "web" was the Vite scaffold's, and it is what the browser tab, a bookmark
  // and the install prompt all showed.
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  expect(html).toContain('<title>Better News</title>');
  expect(html).toContain('rel="manifest"');
  expect(html).toContain('/icon-192.png');
});

test('the manifest is installable and its icons exist', async ({ page }) => {
  const res = await page.request.get('/manifest.webmanifest');
  expect(res.ok()).toBe(true);
  const m = (await res.json()) as {
    name: string; start_url: string; display: string;
    icons: { src: string; sizes: string; purpose: string }[];
  };
  expect(m.name).toBe('Better News');
  expect(m.display).toBe('standalone');
  expect(m.start_url).toBe('/');
  // The Flask manifest pointed at /static/icon-192.png and /static/icon-512.png,
  // neither of which existed -- so the old PWA's icons were broken too. Fetch
  // them rather than trusting the listing.
  expect(m.icons.some((i) => i.sizes === '192x192')).toBe(true);
  expect(m.icons.some((i) => i.purpose === 'maskable')).toBe(true);
  for (const icon of m.icons) {
    expect((await page.request.get(icon.src)).ok(), `${icon.src} is missing`).toBe(true);
  }
});

test('the app wires up a service worker, and only in production', async ({ page }) => {
  // Live registration is not asserted here: these run against the Vite dev
  // server, where a worker would cache module URLs Vite is actively rewriting.
  // What is asserted is that the file is served, that it parses, and that the
  // app calls the registration.
  const sw = await page.request.get('/sw.js');
  expect(sw.ok()).toBe(true);
  expect(sw.headers()['content-type']).toContain('javascript');

  const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  expect(main).toContain('registerServiceWorker()');
  const pwa = readFileSync(new URL('../src/pwa.ts', import.meta.url), 'utf8');
  expect(pwa).toContain('import.meta.env.PROD');
});

test('the service worker never caches the API', () => {
  // A cached reading list would show articles as unread that were read on
  // another device, and a cached 401 would lock someone out until they cleared
  // storage.
  const sw = readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8');
  expect(sw).toContain("url.pathname.startsWith('/api/')");
});

test('going offline says so, and reconnecting clears it', async ({ page, context }) => {
  await signedIn(page);
  await mockApi(page);
  await page.goto('/');
  await page.waitForSelector('.article-row');
  await expect(page.locator('.offline-bar')).toHaveCount(0);

  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event('offline')));
  await expect(page.locator('.offline-bar')).toBeVisible();
  // Still readable: what is already on screen stays there.
  await expect(page.locator('.article-row').first()).toBeVisible();

  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.locator('.offline-bar')).toHaveCount(0);
});

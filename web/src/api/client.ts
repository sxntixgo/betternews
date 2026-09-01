import { BetterNewsClient } from '@shared/api';

/**
 * The app's single client.
 *
 * There is deliberately no token handling here. Signing in sets an HttpOnly
 * session cookie the browser attaches automatically and JavaScript cannot read,
 * so there is nothing to store, nothing to clear, and nothing for injected
 * script to steal. `localStorage` holds display preferences only -- `theme`,
 * `density`, `photos`, `sidebar-collapsed` -- and nothing credential-shaped.
 */

/** Set by the app shell so a 401 anywhere returns the reader to sign-in. */
let onAuthFailure: () => void = () => {};

export function setAuthFailureHandler(fn: () => void) {
  onAuthFailure = fn;
}

export const api = new BetterNewsClient({
  baseUrl: '',
  onAuthFailure: () => onAuthFailure(),
});

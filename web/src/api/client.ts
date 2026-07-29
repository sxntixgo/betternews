import { BetterNewsClient } from '@shared/api';

/**
 * The app's single client.
 *
 * The SPA is served from the same origin as the API, so the base URL is empty
 * and the browser's own session-less fetch carries the bearer token. A native
 * client points the same class at a full origin instead.
 */
const TOKEN_KEY = 'bn.token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(value: string) {
  localStorage.setItem(TOKEN_KEY, value);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/** Set by the app shell so a 401 anywhere returns the reader to sign-in. */
let onAuthFailure: () => void = () => {};

export function setAuthFailureHandler(fn: () => void) {
  onAuthFailure = fn;
}

export const api = new BetterNewsClient({
  baseUrl: '',
  getToken,
  onAuthFailure: () => {
    clearToken();
    onAuthFailure();
  },
});

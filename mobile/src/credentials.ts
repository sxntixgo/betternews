import * as SecureStore from 'expo-secure-store';

/** Where the server is, and the bearer token for it. */
export interface Credentials {
  baseUrl: string;
  token: string;
}

// A token is a password. SecureStore puts it in the iOS keychain and the
// Android keystore; AsyncStorage would leave it in cleartext on disk, readable
// by anything with a backup of the device.
const BASE_URL_KEY = 'betternews.base_url';
const TOKEN_KEY = 'betternews.token';

/**
 * Accepts what a person actually types. `BetterNewsClient` appends `/api/v1`
 * itself, so a base URL that already carries it would produce `/api/v1/api/v1`
 * and a 404 that looks like a bad token.
 */
export function normalizeBaseUrl(input: string): string {
  let url = input.trim();
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  url = url.replace(/\/+$/, '');
  url = url.replace(/\/api\/v1$/i, '');
  return url;
}

export async function loadCredentials(): Promise<Credentials | null> {
  const [baseUrl, token] = await Promise.all([
    SecureStore.getItemAsync(BASE_URL_KEY),
    SecureStore.getItemAsync(TOKEN_KEY),
  ]);
  if (!baseUrl || !token) return null;
  return { baseUrl, token };
}

export async function saveCredentials(creds: Credentials): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(BASE_URL_KEY, creds.baseUrl),
    SecureStore.setItemAsync(TOKEN_KEY, creds.token),
  ]);
}

export async function clearCredentials(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(BASE_URL_KEY),
    SecureStore.deleteItemAsync(TOKEN_KEY),
  ]);
}

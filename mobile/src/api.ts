import { BetterNewsClient } from '@shared/api';

import type { Credentials } from './credentials';

/**
 * The one place a client is built, so the 401 handling is wired the same way
 * every time. Everything else about the API — paths, query strings, wire types
 * — comes from `shared/api.ts` and is not restated here.
 */
export function createClient(
  creds: Credentials,
  onAuthFailure: () => void,
): BetterNewsClient {
  return new BetterNewsClient({
    baseUrl: creds.baseUrl,
    getToken: () => creds.token,
    onAuthFailure,
  });
}

import { ApiError } from '@shared/api';

/**
 * `instanceof` across a bundler boundary is not something to bet the sign-out
 * path on: if the shared file were ever transpiled twice, or classes were
 * downlevelled, the check would quietly start returning false and a 401 would
 * look like a network error. The name/status shape is the fallback.
 */
function asApiError(e: unknown): ApiError | null {
  if (e instanceof ApiError) return e;
  const candidate = e as { name?: unknown; status?: unknown } | null;
  if (candidate && candidate.name === 'ApiError' && typeof candidate.status === 'number') {
    return e as ApiError;
  }
  return null;
}

/** True when the reader has to sign in again. */
export function isAuthFailure(e: unknown): boolean {
  return asApiError(e)?.status === 401;
}

export function describeError(e: unknown): string {
  const api = asApiError(e);
  if (api) return api.message;
  if (e instanceof Error) {
    // `fetch` reports every transport problem as this one opaque string, which
    // tells the reader nothing about which of the two fields they got wrong.
    if (/network request failed/i.test(e.message)) {
      return 'Could not reach the server. Check the URL, and that this device can see it.';
    }
    return e.message;
  }
  return 'Something went wrong.';
}

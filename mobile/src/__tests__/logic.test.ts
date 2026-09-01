/**
 * The decision logic, tested without a renderer.
 *
 * Component-level tests do not run here: @testing-library/react-native 14 fails
 * to render anything under jest-expo with React 19 -- even `render(<Text/>)` --
 * so screens and touch behaviour remain unverified until the app runs on a
 * device. What is covered below is the part that decides *what* happens, which
 * is pure, and is where the mistakes actually live.
 */
import { ApiError, BetterNewsClient, NetworkError, isNetworkError } from '@shared/api';
import type { ArticleState } from '@shared/api';

import { normalizeBaseUrl } from '../credentials';
import { describeError, isAuthFailure } from '../errors';
import { optimisticState } from '../hooks/useArticleActions';

const NEUTRAL: ArticleState = { read: false, saved: false, dismissed: false, opinion: null };

describe('optimistic state', () => {
  it('toggles save, because the API toggles', () => {
    expect(optimisticState(NEUTRAL, 'save').saved).toBe(true);
    expect(optimisticState({ ...NEUTRAL, saved: true }, 'save').saved).toBe(false);
  });

  it('sets a vote, because the API sets', () => {
    // Voting the same way twice is idempotent; treating it as a toggle would
    // un-like an article the reader tapped twice.
    expect(optimisticState(NEUTRAL, 'like').opinion).toBe('liked');
    expect(optimisticState({ ...NEUTRAL, opinion: 'liked' }, 'like').opinion).toBe('liked');
    expect(optimisticState({ ...NEUTRAL, opinion: 'liked' }, 'dislike').opinion).toBe('disliked');
  });

  it('leaves the other fields alone', () => {
    const read = { ...NEUTRAL, read: true, dismissed: true };
    expect(optimisticState(read, 'like')).toMatchObject({ read: true, dismissed: true });
  });
});

describe('auth failures', () => {
  it('recognises a 401', () => {
    expect(isAuthFailure(new ApiError(401, 'revoked'))).toBe(true);
    expect(isAuthFailure(new ApiError(500, 'boom'))).toBe(false);
    expect(isAuthFailure(new Error('offline'))).toBe(false);
  });

  it('recognises one that lost its prototype', () => {
    // The reason the shape check exists: if the shared module were transpiled
    // twice, instanceof would silently fail and a revoked token would look like
    // a network blip -- the reader would never be asked to sign in again.
    expect(isAuthFailure({ name: 'ApiError', status: 401 })).toBe(true);
    expect(isAuthFailure({ name: 'ApiError' })).toBe(false);
  });
});

describe('error messages', () => {
  it('passes the API message through', () => {
    expect(describeError(new ApiError(404, 'No such article.'))).toBe('No such article.');
  });

  it('never returns undefined for a non-Error', () => {
    expect(describeError('a string')).toBeTruthy();
    expect(describeError(null)).toBeTruthy();
  });
});

describe('base URL normalisation', () => {
  it.each([
    ['news.lan', 'http://news.lan'],
    ['  news.lan  ', 'http://news.lan'],
    ['https://news.lan/', 'https://news.lan'],
    ['http://news.lan///', 'http://news.lan'],
    // The client appends /api/v1 itself; leaving it on produces /api/v1/api/v1
    // and a 404 that reads exactly like a bad token.
    ['http://news.lan/api/v1', 'http://news.lan'],
    ['news.lan/api/v1/', 'http://news.lan'],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeBaseUrl(input)).toBe(expected);
  });

  it('leaves an empty entry empty rather than inventing a host', () => {
    expect(normalizeBaseUrl('   ')).toBe('');
  });
});

describe('transport failures', () => {
  // Every engine words a dead connection differently: WebKit and iOS say "Load
  // failed", React Native on Android says "Network request failed", Chrome says
  // "Failed to fetch". Matching those strings is how the phone ended up showing
  // a reader "Load failed" on the sign-in screen. The client types the failure
  // instead, so no caller has to know the engine's vocabulary.
  const engines = [
    ['WebKit and iOS', 'Load failed'],
    ['React Native on Android', 'Network request failed'],
    ['Chrome', 'Failed to fetch'],
  ] as const;

  function clientThatFailsWith(err: unknown) {
    return new BetterNewsClient({
      baseUrl: 'http://news.lan',
      fetchImpl: () => Promise.reject(err),
    });
  }

  it.each(engines)('a %s failure becomes a NetworkError', async (_engine, message) => {
    await expect(clientThatFailsWith(new TypeError(message)).me())
      .rejects.toBeInstanceOf(NetworkError);
  });

  it('is not an auth failure, so it can never sign the reader out', () => {
    // The web shell treated every /me rejection as "signed out", so a server it
    // could not reach was indistinguishable from a revoked session and the
    // reader was dropped on a sign-in form that could not work either.
    expect(isAuthFailure(new NetworkError('Load failed'))).toBe(false);
  });

  it('recognises one that lost its prototype', () => {
    expect(isNetworkError({ name: 'NetworkError' })).toBe(true);
    expect(isNetworkError(new ApiError(401, 'revoked'))).toBe(false);
  });

  it('explains itself without repeating the engine wording', () => {
    const msg = describeError(new NetworkError('Load failed'));
    expect(msg).toMatch(/could not reach the server/i);
    expect(msg).not.toMatch(/load failed/i);
  });

  it('types a failed download too, not only a JSON call', async () => {
    // `download` is a second fetch site with its own error handling; the export
    // buttons went through it and would still have raised a bare TypeError.
    await expect(clientThatFailsWith(new TypeError('Load failed')).exportOpml())
      .rejects.toBeInstanceOf(NetworkError);
  });

  it('leaves a caller\'s abort alone', async () => {
    // Screens abort in-flight requests on unmount. Dressing that up as an
    // unreachable server would put an error banner on a screen already gone.
    const abort = new DOMException('The operation was aborted.', 'AbortError');
    await expect(clientThatFailsWith(abort).me()).rejects.not.toBeInstanceOf(NetworkError);
  });
});

import { useCallback, useMemo, useState } from 'react';

import type { Article, ArticleState, BetterNewsClient } from '@shared/api';

import { describeError, isAuthFailure } from '../errors';

/**
 * A shallow merge into whatever the caller holds for that article.
 *
 * Deliberately partial: the reader holds an `ArticleDetail` and the list holds
 * an `Article`, so spreading a patch keeps `blocks` and `description` intact
 * while still accepting the full `Article` the API returns from an action.
 */
export type MergeArticle = (id: number, patch: Partial<Article>) => void;

export type ActionKind = 'save' | 'like' | 'dislike';

export interface ArticleActions {
  run: (article: Article, kind: ActionKind) => void;
  isPending: (id: number, kind: ActionKind) => boolean;
  error: string | null;
  clearError: () => void;
}

/** What the API will do, applied locally first so the tap feels instant. */
function optimisticState(state: ArticleState, kind: ActionKind): ArticleState {
  switch (kind) {
    // POST /save toggles; the other two set.
    case 'save':
      return { ...state, saved: !state.saved };
    case 'like':
      return { ...state, opinion: 'liked' };
    case 'dislike':
      return { ...state, opinion: 'disliked' };
  }
}

export function useArticleActions(
  client: BetterNewsClient,
  merge: MergeArticle,
): ArticleActions {
  const [pending, setPending] = useState<ReadonlySet<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    (article: Article, kind: ActionKind) => {
      const key = `${article.id}:${kind}`;
      if (pending.has(key)) return;

      const before = article.state;
      merge(article.id, { state: optimisticState(before, kind) });
      setPending((p) => new Set(p).add(key));

      const call =
        kind === 'save'
          ? client.save(article.id)
          : client.vote(article.id, kind === 'like' ? 1 : -1);

      call
        // The response is the authoritative article. Taking it wholesale means
        // the phone never has its own opinion about what a save did.
        .then((updated) => merge(article.id, updated))
        .catch((e: unknown) => {
          merge(article.id, { state: before });
          // A 401 has already torn the session down via `onAuthFailure`; an
          // error banner on top of the sign-in screen would only confuse.
          if (!isAuthFailure(e)) setError(describeError(e));
        })
        .finally(() => {
          setPending((p) => {
            const next = new Set(p);
            next.delete(key);
            return next;
          });
        });
    },
    [client, merge, pending],
  );

  const isPending = useCallback(
    (id: number, kind: ActionKind) => pending.has(`${id}:${kind}`),
    [pending],
  );

  const clearError = useCallback(() => setError(null), []);

  // Memoised because the list's `renderItem` closes over it: a fresh object
  // every render re-renders every visible row on every keystroke elsewhere.
  return useMemo(
    () => ({ run, isPending, error, clearError }),
    [run, isPending, error, clearError],
  );
}

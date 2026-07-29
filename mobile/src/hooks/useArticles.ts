import { useCallback, useEffect, useRef, useState } from 'react';

import type { Article, BetterNewsClient } from '@shared/api';

import { describeError, isAuthFailure } from '../errors';
import type { MergeArticle } from './useArticleActions';

const PAGE_SIZE = 30;

export interface ArticleListState {
  articles: Article[];
  /** The very first load, when there is nothing on screen yet. */
  loading: boolean;
  refreshing: boolean;
  loadingMore: boolean;
  atEnd: boolean;
  error: string | null;
  refresh: () => void;
  loadMore: () => void;
  merge: MergeArticle;
  clearError: () => void;
}

/**
 * `next_offset` is exact — Phase A collapses duplicate clusters in SQL — so
 * this is insurance against two pages fetched either side of a refresh, not a
 * second implementation of the collapsing. Duplicate keys crash a FlatList.
 */
function append(prev: Article[], page: Article[]): Article[] {
  const seen = new Set(prev.map((a) => a.id));
  return [...prev, ...page.filter((a) => !seen.has(a.id))];
}

export function useArticles(client: BetterNewsClient): ArticleListState {
  const [articles, setArticles] = useState<Article[]>([]);
  const [phase, setPhase] = useState<'first' | 'refresh' | 'more' | null>('first');
  const [atEnd, setAtEnd] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refs, not state: `load` has to stay a stable callback or FlatList's
  // onEndReached re-fires on every render that changes the offset.
  const nextOffset = useRef<number | null>(0);
  const busy = useRef(false);

  const load = useCallback(
    async (mode: 'first' | 'refresh' | 'more') => {
      if (busy.current) return;
      const offset = mode === 'more' ? nextOffset.current : 0;
      if (offset === null) return; // already at the end

      busy.current = true;
      setPhase(mode);
      setError(null);
      try {
        const page = await client.articles({ limit: PAGE_SIZE, offset });
        nextOffset.current = page.next_offset;
        setAtEnd(page.next_offset === null);
        setArticles((prev) =>
          mode === 'more' ? append(prev, page.articles) : page.articles,
        );
      } catch (e: unknown) {
        if (!isAuthFailure(e)) setError(describeError(e));
      } finally {
        busy.current = false;
        setPhase(null);
      }
    },
    [client],
  );

  useEffect(() => {
    void load('first');
  }, [load]);

  const refresh = useCallback(() => {
    void load('refresh');
  }, [load]);

  const loadMore = useCallback(() => {
    void load('more');
  }, [load]);

  const merge = useCallback<MergeArticle>((id, patch) => {
    setArticles((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    articles,
    loading: phase === 'first',
    refreshing: phase === 'refresh',
    loadingMore: phase === 'more',
    atEnd,
    error,
    refresh,
    loadMore,
    merge,
    clearError,
  };
}

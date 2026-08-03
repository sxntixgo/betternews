import { useCallback, useEffect, useRef, useState } from 'react';
import type { Article, Diagnosis, ListQuery } from '@shared/api';
import { api } from './client';

/**
 * The reading list, paged.
 *
 * `next_offset` from the API is exact -- duplicate stories are collapsed in SQL
 * before LIMIT/OFFSET -- so appending pages cannot show the same article twice.
 * There is no client-side de-duplication here on purpose; if one is ever
 * needed, the server has regressed.
 */
export function useArticles(query: ListQuery, enabled = true, search = '') {
  const [articles, setArticles] = useState<Article[]>([]);
  // Why the list is empty, when it is. Cleared on search, which has no
  // pipeline to diagnose -- "no feeds yet" under a search for "rockets" would
  // be answering a question nobody asked.
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Identifies the active query, so a slow response from a previous filter
  // cannot land on top of a newer one.
  const key = JSON.stringify({ query, search });
  const active = useRef(key);
  // The in-flight guard has to be a ref, not the `loading` state. State updates
  // are batched, so two IntersectionObserver callbacks in the same tick both
  // read `loading === false`, both fetch the same offset, and both append --
  // the list then shows page one twice. A ref is written synchronously.
  const inFlight = useRef(false);

  const loadPage = useCallback(
    async (offset: number, replace: boolean) => {
      const mine = active.current;
      inFlight.current = true;
      setLoading(true);
      setError(null);
      try {
        // Search is a different endpoint with no paging: it returns the best
        // matches and stops. Treating it as page one keeps one code path.
        if (search) {
          const found = await api.search(search);
          if (active.current !== mine) return;
          setArticles(found.articles);
          setNextOffset(null);
          setDiagnosis(null);
          return;
        }
        const page = await api.articles({ ...query, offset });
        if (active.current !== mine) return;
        setArticles((prev) => (replace ? page.articles : [...prev, ...page.articles]));
        setNextOffset(page.next_offset);
        if (replace) setDiagnosis(page.diagnosis);
      } catch (e) {
        if (active.current === mine) setError((e as Error).message);
      } finally {
        inFlight.current = false;
        if (active.current === mine) setLoading(false);
      }
    },
    [key],  // eslint-disable-line react-hooks/exhaustive-deps
  );

  useEffect(() => {
    // Hooks cannot sit behind the shell's `if (!signedIn) return <SignIn/>`, so
    // without this guard a cold load fires two requests that are certain to
    // 401 -- and the 401 handler then clears a token that was never set.
    if (!enabled) return;
    active.current = key;
    inFlight.current = false;
    setArticles([]);
    setNextOffset(0);
    void loadPage(0, true);
  }, [key, loadPage, enabled]);

  const loadMore = useCallback(() => {
    if (inFlight.current || nextOffset === null) return;
    void loadPage(nextOffset, false);
  }, [nextOffset, loadPage]);

  /** Replace one article in place, for optimistic vote/save updates. */
  const patch = useCallback((updated: Article) => {
    setArticles((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
  }, []);

  return { articles, diagnosis, loading, error, loadMore,
           hasMore: nextOffset !== null, patch };
}

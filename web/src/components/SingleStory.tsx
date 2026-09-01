import { useEffect, useRef, useState } from 'react';
import type { Article } from '@shared/api';
import { relativeTime } from '../relativeTime';

// Matches the layout brief's 250ms cubic-bezier(.2,.8,.2,1) exit, and App.css
// mirrors this duration in `.single-card`'s `transition`. Kept as one number
// here rather than read out of CSS -- there is no cheap way to ask a
// stylesheet its own duration back, so the two are asserted to agree by the
// e2e suite instead.
const EXIT_MS = 250;

/**
 * Triage one story at a time -- an alternative to the reading list, not a
 * replacement for it. Reached from the drawer.
 *
 * Uses `article.summary`, never the full body: `ArticleDetail.blocks` needs a
 * per-article fetch, and a triage flow swiping through fifty stories would
 * issue fifty requests for text nobody stopped to read. `Open` goes to the
 * source for the full article instead.
 *
 * `App.tsx` owns `index` and the mode switch; this component is otherwise
 * stateless about *which* story it is showing.
 */
export function SingleStory({
  articles, index, feedName, onAdvance, onVote, onOpen, onExit,
}: {
  articles: Article[];
  index: number;
  feedName?: (a: Article) => string | undefined;
  onAdvance: (next: number) => void;
  onVote: (a: Article, value: 1 | -1) => void;
  onOpen: (a: Article) => void;
  onExit: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  // Touch state lives in a ref, not React state: a drag repaints on every
  // `touchmove`, and this direct-DOM-write approach (borrowed from
  // `useSwipe`, but scoped to this one card rather than `document`) is what
  // keeps that off the React render loop.
  const drag = useRef({ x0: 0, dragging: false });
  const [leaving, setLeaving] = useState<'left' | 'right' | null>(null);

  // A fresh card per article: a drag or an exit transform left over from the
  // previous story must never bleed into the next one.
  useEffect(() => {
    setLeaving(null);
    const el = cardRef.current;
    if (el) {
      el.style.transition = '';
      el.style.transform = '';
    }
  }, [index]);

  const article = articles[index];
  // Interface contract: render nothing when there is nothing to triage.
  if (!article) return null;

  function commit(direction: 'left' | 'right', value: 1 | -1) {
    onVote(article, value);
    const el = cardRef.current;
    // Clear any inline transform a drag left behind so the CSS class below
    // -- not a stale inline style -- drives the exit.
    if (el) { el.style.transition = ''; el.style.transform = ''; }
    setLeaving(direction);
    window.setTimeout(() => {
      const next = index + 1;
      if (next >= articles.length) onExit();
      else onAdvance(next);
    }, EXIT_MS);
  }

  function onTouchStart(e: React.TouchEvent) {
    drag.current = { x0: e.touches[0].clientX, dragging: false };
  }

  function onTouchMove(e: React.TouchEvent) {
    const el = cardRef.current;
    if (!el) return;
    const dx = e.touches[0].clientX - drag.current.x0;
    if (!drag.current.dragging) {
      if (Math.abs(dx) < 8) return;
      drag.current.dragging = true;
    }
    el.style.transform = `translateX(${dx}px)`;
  }

  function onTouchEnd(e: React.TouchEvent) {
    const el = cardRef.current;
    if (!el || !drag.current.dragging) return;
    const dx = e.changedTouches[0].clientX - drag.current.x0;
    const ratio = Math.abs(dx) / el.offsetWidth;
    drag.current.dragging = false;
    if (ratio > 0.4) {
      // Swipe right = Up, swipe left = Down.
      if (dx > 0) commit('right', 1);
      else commit('left', -1);
      return;
    }
    el.style.transition = `transform ${EXIT_MS}ms cubic-bezier(.2,.8,.2,1)`;
    el.style.transform = '';
    window.setTimeout(() => { if (el) el.style.transition = ''; }, EXIT_MS);
  }

  const score = article.score === null ? null : Math.round(article.score * 100);
  const source = feedName?.(article);
  const age = relativeTime(article.published_at);
  const cardClass = leaving ? `single-card leaving-${leaving}` : 'single-card';

  return (
    <div className="single-story">
      <div className="single-top">
        <span className="single-counter">{index + 1} OF {articles.length}</span>
        <button type="button" className="single-exit" onClick={onExit}>Feeds</button>
      </div>

      <div
        className={cardClass}
        ref={cardRef}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {/* Omitted entirely, not an empty box, when there is no photo -- the
            list card makes the same call for the same reason. */}
        {article.thumbnail_url && (
          <img className="single-image" src={article.thumbnail_url} alt="" />
        )}
        <div className="single-body">
          <div className="single-meta">
            {/* The pill is retained here and nowhere else: the list card
                deliberately shows a bare gold number, and a full pill would
                restate that decision for one story instead of all of them. */}
            {score !== null && <span className="score-pill">{score}</span>}
            {source && <span className="single-source">{source}</span>}
            {age && <span className="single-age">{age}</span>}
          </div>
          <h2 className="single-headline">{article.title}</h2>
          {article.summary && <p className="single-summary">{article.summary}</p>}
          {article.topics.length > 0 && (
            <p className="single-tags">{article.topics.join(' · ')}</p>
          )}
        </div>
      </div>

      <div className="single-actions">
        <button type="button" className="single-vote single-vote-down" onClick={() => commit('left', -1)}>
          Down
        </button>
        <button type="button" className="single-open" onClick={() => onOpen(article)}>
          Open
        </button>
        <button type="button" className="single-vote single-vote-up" onClick={() => commit('right', 1)}>
          Up
        </button>
      </div>
    </div>
  );
}

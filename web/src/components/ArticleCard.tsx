import type { Article } from '@shared/api';
import { relativeTime } from '../relativeTime';
import { swipeJustHandled } from '../useSwipe';

/**
 * One row of the reading list.
 *
 * Everything shown here was decided by the server: `title` is already the
 * de-clickbaited headline and `duplicate_count` is how many other feeds carried
 * the same story. Nothing is re-derived, so this and the API's own idea of an
 * article cannot drift.
 */
export function ArticleCard({
  article,
  onOpen,
  onVote,
  onSave,
  onTopic,
  feedName,
  focused,
}: {
  article: Article;
  onOpen: (a: Article) => void;
  onVote: (a: Article, value: 1 | -1) => void;
  onSave: (a: Article) => void;
  onTopic?: (topic: string) => void;
  /** Which paper ran it. Resolved by the shell, which already holds the feed
   *  list for the sidebar; the article only carries `feed_id`. */
  feedName?: string;
  focused?: boolean;
}) {
  /**
   * The card opens the reader. Only the title did before, which is a small
   * target on a phone and not the one a reader aims at -- the thumbnail and the
   * summary read as part of the same thing.
   *
   * Guarded by `closest` rather than by attaching the handler to three separate
   * elements: the card also carries the save, like, dislike and topic buttons
   * and an "Open in browser" link, and every one of them would otherwise open
   * the reader as well as doing its own job. Asking the event where it came
   * from keeps that true for anything added later, which three hand-placed
   * handlers would not.
   */
  function openFromBody(e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest('button, a, input, select, textarea')) return;
    if (swipeJustHandled()) return;
    onOpen(article);
  }

  // Declared, deliberately unused. The desktop meta line carries one topic
  // again, but as plain text rather than as a control: a tag that filters the
  // list is a second thing to press on a line that already holds four, and the
  // card itself opens the reader. The prop stays in the signature so making
  // that tag clickable later is a change here and nowhere else.
  void onTopic;

  const s = article.state;
  const classes = [
    'article-row',
    s.opinion ?? '',
    s.read ? 'read' : '',
    s.saved ? 'saved' : '',
    s.dismissed ? 'dismissed' : '',
    focused ? 'focused' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const score = article.score === null ? null : Math.round(article.score * 100);

  return (
    // Same id the server-rendered card uses, so anchoring, deep links and tests
    // can address a row without depending on its position in the list.
    <article className={classes} id={`card-${article.id}`} onClick={openFromBody}>
      {/* Two rows now, not four. The story, then one line carrying everything
          a reader reads *and* everything they press. The four-row card put the
          score, the buttons, the source and the tags on separate lines, which
          is most of the vertical space this redesign reclaims. */}
      <div className="article-head">
        <div className="article-text">
          {/* Still a span, not a <button>: a button is an atomic inline-level
              box in every engine, so it cannot wrap around a float and gets
              pushed below one whole. role/tabIndex/onKeyDown give back exactly
              what <button> provided. */}
          <span
            className="article-title"
            role="button"
            tabIndex={0}
            onClick={() => onOpen(article)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpen(article);
              }
            }}
          >
            {article.title}
          </span>
          {article.summary && <p className="article-summary">{article.summary}</p>}
          {article.hidden && article.score_reason && (
            <p className="hidden-reason">Hidden: {article.score_reason}</p>
          )}
        </div>
        {article.thumbnail_url && (
          <img className="article-thumb" src={article.thumbnail_url} alt="" loading="lazy" />
        )}
      </div>

      <div className="article-meta">
        <div className="meta-facts">
          {score !== null && (
            <span className="meta-score" title={article.score_reason ?? ''}>
              {score}
            </span>
          )}
          {feedName && <span className="meta-source">{feedName}</span>}
          {relativeTime(article.published_at) && (
            <>
              <span className="meta-dot">·</span>
              <span className="meta-age">{relativeTime(article.published_at)}</span>
            </>
          )}
          {article.duplicate_count > 0 && (
            <>
              <span className="meta-dot">·</span>
              {/* The mock's "comment count" slot. Better News has no comments;
                  this is how many other feeds carried the same story. */}
              <span className="meta-dupes" title="Other feeds carrying this story">
                {article.duplicate_count}
              </span>
            </>
          )}
          {/* One topic, plain text, and only where there is room for it: the
              meta line is a single line on a phone and this is the item that
              would wrap it. Rendered at every width and hidden by CSS below
              900px -- the card must not hold its own copy of the breakpoint. */}
          {article.topics[0] && (
            <>
              <span className="meta-dot meta-dot-tag">·</span>
              <span className="meta-tag">{article.topics[0]}</span>
            </>
          )}
        </div>

        <div className="article-actions">
          {/* The reading list's way out to the publisher, back after the
              four-row card took it with the rest of that row. Class
              `action-open` and *not* `action`: it is display:none below 900px,
              and mobile.spec's tap-target sweep measures every
              `.article-actions .action` -- an element with no box has no tap
              target and no bounding box to measure. It shares the styling
              through a grouped selector instead. */}
          <a
            className="action-open"
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open
          </a>
          <button
            className="action action-save"
            aria-pressed={s.saved}
            onClick={() => onSave(article)}
          >
            {s.saved ? 'Saved' : 'Save'}
          </button>
          <button
            className="action"
            aria-pressed={s.opinion === 'liked'}
            disabled={s.opinion === 'liked'}
            onClick={() => onVote(article, 1)}
          >
            Up
          </button>
          <button
            className="action"
            aria-pressed={s.opinion === 'disliked'}
            disabled={s.opinion === 'disliked'}
            onClick={() => onVote(article, -1)}
          >
            Down
          </button>
        </div>
      </div>
    </article>
  );
}

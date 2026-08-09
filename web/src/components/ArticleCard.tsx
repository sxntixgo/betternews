import type { Article } from '@shared/api';
import { relativeTime } from '../relativeTime';
import { swipeJustHandled } from '../useSwipe';

/**
 * One row of the reading list.
 *
 * Everything shown here was decided by the server: `title` is already the
 * de-clickbaited headline, `original_title` is non-null only when it really was
 * rewritten, and `reading_time` is parsed upstream. Nothing is re-derived, so
 * this and the HTML card cannot drift.
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

  return (
    // Same id the server-rendered card uses, so anchoring, deep links and tests
    // can address a row without depending on its position in the list.
    <article className={classes} id={`card-${article.id}`} onClick={openFromBody}>
      {/* The thumbnail is its own grid cell, not part of the metadata. It used
          to share a 72px column with the reading time, the source and the age,
          which stacked them into a 96px tower and set the card's height. */}
      {article.thumbnail_url && (
        <img className="article-thumb" src={article.thumbnail_url} alt="" loading="lazy" />
      )}

      <div className="article-left">
        {article.reading_time && <span className="reading-time">🕐 {article.reading_time}</span>}
        {/* Which paper ran it and how old it is: the two things a reader weighs
            before opening a headline, and neither was shown before. */}
        {feedName && <span className="article-source">{feedName}</span>}
        {relativeTime(article.published_at) && (
          <span className="article-age">{relativeTime(article.published_at)}</span>
        )}
        <a className="btn-external" href={article.url} target="_blank" rel="noopener noreferrer">
          ↗ Open
        </a>
      </div>

      <div className="article-content">
        <div className="article-row-header">
          {article.score !== null && (
            <span className="pill score-badge" title={article.score_reason ?? ''}>
              {Math.round(article.score * 100)}%
            </span>
          )}
          <button className="article-title" onClick={() => onOpen(article)}>
            {article.title}
          </button>
        </div>

        {article.original_title && (
          <p className="original-title">Originally: {article.original_title}</p>
        )}
        {article.duplicate_count > 0 && (
          <p className="dup-note">
            + {article.duplicate_count} other feed{article.duplicate_count === 1 ? '' : 's'}
          </p>
        )}
        {article.summary && <p className="article-summary">{article.summary}</p>}
        {/* Visible text, not a tooltip on the score badge. The hidden list is
            reviewed on a phone, where there is no hover. */}
        {article.hidden && article.score_reason && (
          <p className="hidden-reason">Hidden: {article.score_reason}</p>
        )}
      </div>

      {/* A sibling of the content, not inside it: on a phone the grid puts this
          on the same line as the reading time and the actions, so the tags cost
          nothing vertically. Inside `.article-content` they were a row of their
          own, 26px on every card. */}
      {article.topics.length > 0 && (
        <p className="topic-chips">
          {/* The kind reads differently from a topic: it is the shape of the
              story, and the reader may want one shape of a subject and not
              another. */}
          {article.kind && article.kind !== 'news' && (
            <span className="pill kind-chip">{article.kind}</span>
          )}
          {article.topics.map((t) => (
            <button className="pill topic-chip" key={t} onClick={() => onTopic?.(t)}>
              {t}
            </button>
          ))}
        </p>
      )}

      {/* A column of the row, right of the text -- same as the server UI, so the
          title and summary stop at the same edge. */}
      <div className="article-actions-inline">
        <button
          className="btn-icon btn-save"
          aria-pressed={s.saved}
          title={s.saved ? 'Unsave' : 'Save for later'}
          onClick={() => onSave(article)}
        >
          {s.saved ? '★' : '☆'}
        </button>
        <button
          className="btn-icon btn-like"
          disabled={s.opinion === 'liked'}
          title="Like"
          onClick={() => onVote(article, 1)}
        >
          👍
        </button>
        <button
          className="btn-icon btn-dislike"
          disabled={s.opinion === 'disliked'}
          title="Dislike"
          onClick={() => onVote(article, -1)}
        >
          👎
        </button>
      </div>
    </article>
  );
}

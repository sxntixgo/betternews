import type { Article } from '@shared/api';

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
  focused,
}: {
  article: Article;
  onOpen: (a: Article) => void;
  onVote: (a: Article, value: 1 | -1) => void;
  onSave: (a: Article) => void;
  onTopic?: (topic: string) => void;
  focused?: boolean;
}) {
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
    <article className={classes} id={`card-${article.id}`}>
      <div className="article-left">
        {article.thumbnail_url && (
          <img className="article-thumb" src={article.thumbnail_url} alt="" loading="lazy" />
        )}
        {article.reading_time && <span className="reading-time">🕐 {article.reading_time}</span>}
        <a className="btn-external" href={article.url} target="_blank" rel="noopener noreferrer">
          ↗ Open
        </a>
      </div>

      <div className="article-content">
        <div className="article-row-header">
          {article.score !== null && (
            <span className="score-badge" title={article.score_reason ?? ''}>
              {Math.round(article.score * 100)}%
            </span>
          )}
          <span className="article-title" onClick={() => onOpen(article)}>
            {article.title}
          </span>
        </div>

        {article.original_title && (
          <p className="original-title">Originally: {article.original_title}</p>
        )}
        {article.duplicate_count > 0 && (
          <p className="dup-note">
            + {article.duplicate_count} other feed{article.duplicate_count === 1 ? '' : 's'}
          </p>
        )}
        {article.topics.length > 0 && (
          <p className="topic-chips">
            {article.topics.map((t) => (
              <button className="topic-chip" key={t} onClick={() => onTopic?.(t)}>
                {t}
              </button>
            ))}
          </p>
        )}
        {article.summary && <p className="article-summary">{article.summary}</p>}
        {/* Visible text, not a tooltip on the score badge. The hidden list is
            reviewed on a phone, where there is no hover. */}
        {article.hidden && article.score_reason && (
          <p className="hidden-reason">Hidden: {article.score_reason}</p>
        )}
      </div>

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

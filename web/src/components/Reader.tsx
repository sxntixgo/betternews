import { useEffect, useState } from 'react';
import type { ArticleDetail } from '@shared/api';
import { api } from '../api/client';

/**
 * The reader.
 *
 * `blocks` arrive already split and classified by the server, so this renders
 * them rather than parsing anything. A group with a non-null `aside` is
 * older-news padding: it is folded, never dropped, so a misclassification is
 * one click away from being read -- the same rule the HTML reader follows.
 */
export function Reader({ id, onClose }: { id: number; onClose: () => void }) {
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .article(id)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <nav className="modal-nav">
          <button className="btn-icon" onClick={onClose}>
            ← Back
          </button>
          {detail && (
            <a className="btn-external" href={detail.url} target="_blank" rel="noopener noreferrer">
              ↗ Open in browser
            </a>
          )}
        </nav>

        <div className="modal-body">
          {error && <p className="error">{error}</p>}
          {!detail && !error && <p className="muted">Loading…</p>}
          {detail && (
            <>
              <h1>{detail.title}</h1>
              {detail.original_title && (
                <p className="original-title">Originally: {detail.original_title}</p>
              )}
              {detail.description && <p className="lede">{detail.description}</p>}
              {detail.blocks.map((group, i) =>
                group.aside ? (
                  <details className="aside-group" key={i}>
                    <summary>{group.label ?? 'Aside'}</summary>
                    {group.blocks.map((b, j) => (
                      <BlockView block={b} key={j} />
                    ))}
                  </details>
                ) : (
                  group.blocks.map((b, j) => <BlockView block={b} key={`${i}-${j}`} />)
                ),
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function BlockView({ block }: { block: ArticleDetail['blocks'][number]['blocks'][number] }) {
  if (block.type === 'ul') {
    return (
      <ul>
        {block.items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    );
  }
  if (block.type === 'embed') {
    // The server recognised a bare Twitter/Instagram permalink. Without the
    // official widget scripts, a link is honest and works.
    return (
      <p className="embed">
        <a href={block.url} target="_blank" rel="noopener noreferrer">
          {block.platform} post
        </a>
      </p>
    );
  }
  return <p>{block.text}</p>;
}

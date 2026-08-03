import { useCallback, useState } from 'react';
import type { Feed, FeedList } from '@shared/api';

/**
 * The feed list, grouped by tag.
 *
 * The server-rendered sidebar did this and the SPA did not: it showed one flat
 * list and ignored `Feed.tags` entirely, so tagging feeds was a feature you
 * could use in Manage Feeds and then never see the effect of.
 *
 * Groups collapse, and the collapsed set is remembered — with thirty feeds
 * across six tags the whole point is to keep the ones you are not reading shut,
 * and re-collapsing them on every load would make the feature worse than the
 * flat list it replaces.
 */
const COLLAPSE_KEY = 'sidebar-collapsed';

function loadCollapsed(): Set<string> {
  // A UI preference, not a credential — the sanctioned kind of localStorage.
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export interface SidebarProps {
  feeds: FeedList | null;
  feed: number | undefined;
  saved: boolean;
  hidden: boolean;
  onAll: () => void;
  onFeed: (id: number) => void;
  onSaved: () => void;
  onHidden: () => void;
  /** A feed *within* Hidden: keeps the hidden filter rather than clearing it. */
  onHiddenFeed: (id: number) => void;
  /** Admin only, and omitted for everyone else rather than shown disabled. */
  onManageFeeds?: () => void;
}

/** Feeds under each tag, plus whatever carries no tag at all. */
function group(feeds: Feed[]): { tags: [string, Feed[]][]; untagged: Feed[] } {
  const byTag = new Map<string, Feed[]>();
  const untagged: Feed[] = [];
  for (const f of feeds) {
    if (f.tags.length === 0) {
      untagged.push(f);
      continue;
    }
    // A feed with two tags appears under both. It is one subscription seen from
    // two angles, not a thing that has to pick a home.
    for (const t of f.tags) {
      const bucket = byTag.get(t);
      if (bucket) bucket.push(f);
      else byTag.set(t, [f]);
    }
  }
  return {
    tags: [...byTag.entries()].sort(([a], [b]) => a.localeCompare(b)),
    untagged,
  };
}

export function Sidebar({
  feeds, feed, saved, hidden, onAll, onFeed, onSaved, onHidden, onHiddenFeed,
  onManageFeeds,
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);

  const toggle = useCallback((name: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(name)) next.add(name);
      try {
        localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...next]));
      } catch {
        /* private mode: the grouping still works, it just forgets */
      }
      return next;
    });
  }, []);

  const { tags, untagged } = group(feeds?.feeds ?? []);
  // With no tags anywhere, a "Feeds" heading over the same list is a second
  // name for the thing above it. Nest them under All feeds instead.
  const flat = tags.length === 0;

  const feedButton = (f: Feed) => (
    <button
      key={f.id}
      className={`sidebar-feed sidebar-feed-nested ${feed === f.id ? 'active' : ''}`}
      onClick={() => onFeed(f.id)}
    >
      <span className="sidebar-feed-title">{f.title}</span>
      {f.unread > 0 && <span className="sidebar-feed-count">{f.unread}</span>}
    </button>
  );

  const group_ = (name: string, label: string, rows: Feed[]) => {
    const shut = collapsed.has(name);
    return (
      <div className={`sidebar-group ${shut ? 'collapsed' : ''}`} key={name}>
        <div className="sidebar-group-header">
          <button
            className="sidebar-collapse"
            aria-expanded={!shut}
            aria-label={`${shut ? 'Expand' : 'Collapse'} ${label}`}
            onClick={() => toggle(name)}
          >
            ▾
          </button>
          <span className="sidebar-group-title sidebar-tag-label">{label}</span>
        </div>
        {!shut && <div className="sidebar-group-body">{rows.map(feedButton)}</div>}
      </div>
    );
  };

  return (
    <>
      <div className="sidebar-group">
        <div className="sidebar-group-header">
          <button
            className={`sidebar-feed sidebar-group-title ${feed === undefined && !saved && !hidden ? 'active' : ''}`}
            onClick={onAll}
          >
            <span className="sidebar-feed-title">All feeds</span>
            {feeds && feeds.unread > 0 && (
              <span className="sidebar-feed-count">{feeds.unread}</span>
            )}
          </button>
          {/* Where the server UI kept it: beside the list it edits, not buried
              in a menu. */}
          {onManageFeeds && (
            <button className="btn-icon sidebar-manage" title="Manage feeds"
                    aria-label="Manage feeds" onClick={onManageFeeds}>
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <path fill="none" stroke="currentColor" strokeWidth="1.8"
                      strokeLinecap="round" strokeLinejoin="round"
                      d="M12 20h9 M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
          )}
        </div>
        {flat && <div className="sidebar-group-body">{untagged.map(feedButton)}</div>}
      </div>

      {tags.map(([tag, rows]) => group_(`tag-${tag}`, tag, rows))}
      {!flat && untagged.length > 0 && group_('untagged', 'Untagged', untagged)}

      <button
        className={`sidebar-feed ${saved ? 'active' : ''}`}
        onClick={onSaved}
      >
        <span className="sidebar-feed-title">Saved</span>
        {feeds && feeds.saved > 0 && <span className="sidebar-feed-count">{feeds.saved}</span>}
      </button>

      <div className={`sidebar-group ${collapsed.has('hidden') ? 'collapsed' : ''}`}>
        <div className="sidebar-group-header">
          <button
            className="sidebar-collapse"
            aria-expanded={!collapsed.has('hidden')}
            aria-label={`${collapsed.has('hidden') ? 'Expand' : 'Collapse'} Hidden`}
            onClick={() => toggle('hidden')}
          >
            ▾
          </button>
          <button
            className={`sidebar-feed sidebar-group-title ${hidden ? 'active' : ''}`}
            onClick={onHidden}
          >
            <span className="sidebar-feed-title">Hidden</span>
            {feeds && feeds.hidden > 0 && (
              <span className="sidebar-feed-count">{feeds.hidden}</span>
            )}
          </button>
        </div>
        {/* Per-feed hidden counts, so "everything I subscribed to is below the
            threshold" is distinguishable from "one noisy feed is". */}
        {!collapsed.has('hidden') && (
          <div className="sidebar-group-body">
            {(feeds?.feeds ?? []).filter((f) => f.hidden > 0).map((f) => (
              <button
                key={f.id}
                className={`sidebar-feed sidebar-feed-nested ${hidden && feed === f.id ? 'active' : ''}`}
                onClick={() => onHiddenFeed(f.id)}
              >
                <span className="sidebar-feed-title">{f.title}</span>
                <span className="sidebar-feed-count">{f.hidden}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

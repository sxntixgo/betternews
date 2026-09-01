import { useCallback, useState } from 'react';
import type { Feed, FeedList } from '@shared/api';

/**
 * The feed list, grouped by tag: the drawer's first group.
 *
 * It has no heading any more. The drawer used to be five all-caps labelled
 * sections and "FEEDS" over a list of feeds was the emptiest of the five --
 * the rows underneath already say what they are. What replaces the label is
 * the indent: the children hang behind a 2px rule, so the nesting is what
 * carries the grouping rather than a word.
 *
 * `Hidden` moved out of here into `HiddenFeeds` below, because it belongs
 * beside Saved in the second group -- both are lists of articles held back
 * from the reading list, and neither answers "which source".
 *
 * The server-rendered sidebar grouped by tag and the SPA did not: it showed
 * one flat list and ignored `Feed.tags` entirely, so tagging feeds was a
 * feature you could use in Manage Feeds and then never see the effect of.
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

/**
 * The collapsed set, shared by two components through localStorage.
 *
 * `Sidebar` and `HiddenFeeds` are separate elements in separate groups now but
 * still write one key, so the toggle re-reads storage instead of flipping a
 * snapshot taken when the component mounted. Without that, collapsing a tag
 * group and then collapsing Hidden would write Hidden's stale copy back and
 * silently re-open the tag.
 */
function useCollapsed() {
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);
  const toggle = useCallback((name: string) => {
    const next = loadCollapsed();
    if (!next.delete(name)) next.add(name);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...next]));
    } catch {
      /* private mode: the grouping still works, it just forgets */
    }
    setCollapsed(next);
  }, []);
  return [collapsed, toggle] as const;
}

export interface SidebarProps {
  feeds: FeedList | null;
  feed: number | undefined;
  saved: boolean;
  hidden: boolean;
  onAll: () => void;
  onFeed: (id: number) => void;
  /** Admin only, and omitted for everyone else rather than shown disabled. */
  onManageFeeds?: () => void;
}

export interface HiddenFeedsProps {
  feeds: FeedList | null;
  feed: number | undefined;
  hidden: boolean;
  onHidden: () => void;
  /** A feed *within* Hidden: keeps the hidden filter rather than clearing it. */
  onHiddenFeed: (id: number) => void;
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

/** The count beside a row: a bare number, gold on All feeds and muted below. */
function Count({ n }: { n: number }) {
  // `pill` and `sidebar-feed-count` are the app's one pill shape, kept for the
  // touch-target height; the redesign only takes the fill off it.
  return <span className="pill sidebar-feed-count count">{n}</span>;
}

export function Sidebar({
  feeds, feed, saved, hidden, onAll, onFeed, onManageFeeds,
}: SidebarProps) {
  const [collapsed, toggle] = useCollapsed();

  const { tags, untagged } = group(feeds?.feeds ?? []);
  // With no tags anywhere there is nothing to group by, so the feeds hang
  // straight off the indent rule rather than under a single "Untagged".
  const flat = tags.length === 0;
  const allActive = feed === undefined && !saved && !hidden;

  const feedButton = (f: Feed) => (
    <button
      key={f.id}
      className={`sidebar-feed sidebar-feed-nested ${feed === f.id ? 'active' : ''}`}
      onClick={() => onFeed(f.id)}
    >
      <span className="sidebar-feed-title">{f.title}</span>
      {f.unread > 0 && <Count n={f.unread} />}
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
      <div className="drawer-all">
        <button
          className={`drawer-item is-all ${allActive ? 'active' : ''}`}
          onClick={onAll}
        >
          <span className="sidebar-feed-title">All feeds</span>
          {feeds && feeds.unread > 0 && <Count n={feeds.unread} />}
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

      {/* The indent rule. It goes gold while one of these feeds is the list
          being read, which is the whole of what the old "FEEDS" label and the
          row tint used to do between them. */}
      <div className={`drawer-children ${feed !== undefined && !hidden ? 'is-active' : ''}`}>
        {flat
          ? untagged.map(feedButton)
          : (
            <>
              {tags.map(([tag, rows]) => group_(`tag-${tag}`, tag, rows))}
              {untagged.length > 0 && group_('untagged', 'Untagged', untagged)}
            </>
          )}
      </div>
    </>
  );
}

/**
 * Hidden, and the per-feed counts under it.
 *
 * Its own component since the split: it sits in the drawer's second group with
 * Saved and Your stats, and the feeds it lists are not the feeds above.
 * Per-feed counts, so "everything I subscribed to is below the threshold" is
 * distinguishable from "one noisy feed is".
 */
export function HiddenFeeds({
  feeds, feed, hidden, onHidden, onHiddenFeed,
}: HiddenFeedsProps) {
  const [collapsed, toggle] = useCollapsed();
  const shut = collapsed.has('hidden');

  return (
    <div className={`sidebar-group ${shut ? 'collapsed' : ''}`}>
      <div className="sidebar-group-header">
        <button
          className="sidebar-collapse"
          aria-expanded={!shut}
          aria-label={`${shut ? 'Expand' : 'Collapse'} Hidden`}
          onClick={() => toggle('hidden')}
        >
          ▾
        </button>
        <button
          className={`sidebar-feed ${hidden ? 'active' : ''}`}
          onClick={onHidden}
        >
          <span className="sidebar-feed-title">Hidden</span>
          {feeds && feeds.hidden > 0 && <Count n={feeds.hidden} />}
        </button>
      </div>
      {!shut && (
        <div className="sidebar-group-body">
          {(feeds?.feeds ?? []).filter((f) => f.hidden > 0).map((f) => (
            <button
              key={f.id}
              className={`sidebar-feed sidebar-feed-nested ${hidden && feed === f.id ? 'active' : ''}`}
              onClick={() => onHiddenFeed(f.id)}
            >
              <span className="sidebar-feed-title">{f.title}</span>
              <Count n={f.hidden} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

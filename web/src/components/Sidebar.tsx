import { useCallback, useState } from 'react';
import type { Feed, FeedList, Folder } from '@shared/api';

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
  /** The open folder's id, if the list being read is one. */
  folder?: number;
  saved: boolean;
  hidden: boolean;
  onAll: () => void;
  /** Read every feed in a folder as one list. */
  onFolder?: (id: number) => void;
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

/** Feeds under each folder, in the folders' own (alphabetical) order, plus
 *  the feeds filed nowhere. Empty folders are kept: one made a moment ago has
 *  to show before anything is filed in it. */
function group(list: FeedList | null): { folders: [Folder, Feed[]][]; unfiled: Feed[] } {
  const byFolder = new Map<number, Feed[]>();
  for (const d of list?.folders ?? []) byFolder.set(d.id, []);
  const unfiled: Feed[] = [];
  for (const f of list?.feeds ?? []) {
    const bucket = f.folder_id === null ? undefined : byFolder.get(f.folder_id);
    if (bucket) bucket.push(f);
    else unfiled.push(f);
  }
  return {
    folders: (list?.folders ?? []).map((d) => [d, byFolder.get(d.id) ?? []]),
    unfiled,
  };
}

/**
 * The count beside a row: a bare number, gold on the three top-level lists --
 * All feeds, Saved and Hidden -- and muted on the feeds nested under them.
 */
function Count({ n }: { n: number }) {
  // Plain text, not a pill. `.pill` survives only in Settings, where it was
  // never removed by the redesign.
  return <span className="sidebar-feed-count">{n}</span>;
}

export function Sidebar({
  feeds, feed, folder, saved, hidden, onAll, onFeed, onFolder, onManageFeeds,
}: SidebarProps) {
  const [collapsed, toggle] = useCollapsed();
  // 'all' -- distinct from 'hidden' and from the `tag-${tag}` / 'untagged'
  // keys the tag groups below use, so collapsing this row cannot collide
  // with any of them in the one shared localStorage set.
  const shut = collapsed.has('all');

  const { folders, unfiled } = group(feeds);
  // With no folders at all there is nothing to group by, so the feeds hang
  // straight off the indent rule rather than under a single "No folder".
  const flat = folders.length === 0;
  const allActive = feed === undefined && folder === undefined && !saved && !hidden;

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

  /** `id` is set for a real folder; "No folder" has nothing to ask the server
   *  for, so its label stays a plain heading. */
  const group_ = (name: string, label: string, rows: Feed[], id?: number) => {
    const shut = collapsed.has(name);
    const unread = rows.reduce((n, f) => n + f.unread, 0);
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
          {id !== undefined && onFolder ? (
            // The name opens the folder; the caret beside it only collapses.
            <button
              className={`sidebar-folder ${folder === id && !hidden ? 'active' : ''}`}
              onClick={() => onFolder(id)}
            >
              <span className="sidebar-group-title sidebar-tag-label">{label}</span>
              {unread > 0 && <Count n={unread} />}
            </button>
          ) : (
            <span className="sidebar-group-title sidebar-tag-label">{label}</span>
          )}
        </div>
        {/* No body for an empty folder: its gap would read as a missing row. */}
        {!shut && rows.length > 0 && (
          <div className="sidebar-group-body">{rows.map(feedButton)}</div>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="drawer-all">
        <button
          className={`drawer-item is-lead ${allActive ? 'active' : ''}`}
          onClick={onAll}
        >
          <span className="sidebar-feed-title">All feeds</span>
          {feeds && feeds.unread > 0 && <Count n={feeds.unread} />}
        </button>
        {/* The caret sits right after the row -- trailing edge, matching
            Hidden's shape, not leading a chevron-indented label the way the
            tag groups below do. The manage-feeds pencil (admin only) comes
            last, after the caret: it opens a different screen entirely
            (Manage Feeds) rather than toggling this list, so it sits outside
            the row/caret pair the other two form together, the same way it
            already trailed the row before the caret existed. */}
        <button
          className="sidebar-collapse"
          aria-expanded={!shut}
          aria-label={`${shut ? 'Expand' : 'Collapse'} All feeds`}
          onClick={() => toggle('all')}
        >
          ▾
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
          row tint used to do between them. Collapsing hides this element only
          -- Saved, Hidden and everything below live in their own
          `.drawer-group`s and never see `shut`. */}
      {!shut && (
        <div className={`drawer-children ${feed !== undefined && !hidden ? 'is-active' : ''}`}>
          {flat
            ? unfiled.map(feedButton)
            : (
              <>
                {folders.map(([d, rows]) => group_(`folder-${d.id}`, d.name, rows, d.id))}
                {unfiled.length > 0 && group_('unfiled', 'No folder', unfiled)}
              </>
            )}
        </div>
      )}
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
      {/* The caret comes after the row, not before it. Hidden is one of the
          three top-level lists -- All feeds, Saved, Hidden -- and three rows
          set alike do not read as peers unless they also start at the same x.
          Led by the caret this one began 42px in on a phone (the tap-target
          floor) and 16px on a desktop: level with its own children, which is
          the one place a parent must not sit. It still has children and they
          still collapse, so the caret could not simply go; at the trailing
          edge it keeps the affordance and stops displacing the label. The
          cost is the unread count sitting a caret's width off the right edge,
          which is the lesser misalignment: the labels are what a reader scans
          down, the counts are what they glance at. */}
      <div className="sidebar-group-header">
        <button
          className={`sidebar-feed is-lead ${hidden ? 'active' : ''}`}
          onClick={onHidden}
        >
          <span className="sidebar-feed-title">Hidden</span>
          {feeds && feeds.hidden > 0 && <Count n={feeds.hidden} />}
        </button>
        <button
          className="sidebar-collapse"
          aria-expanded={!shut}
          aria-label={`${shut ? 'Expand' : 'Collapse'} Hidden`}
          onClick={() => toggle('hidden')}
        >
          ▾
        </button>
      </div>
      {/* `.drawer-children`, not `.sidebar-group-body` -- Hidden gets the same
          indent rule All feeds' children draw (border-left, gold while one of
          these is the list being read) rather than a second copy of it.
          `.hidden-children` carries the wider indent that used to live on
          `.sidebar-group-body` alone; see the comment on `.drawer-children`
          in App.css. */}
      {!shut && (
        <div className={`drawer-children hidden-children ${hidden && feed !== undefined ? 'is-active' : ''}`}>
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

/**
 * The unread count, drawn into the tab icon.
 *
 * A canvas rather than a set of pre-rendered PNGs: the count is unbounded and
 * the colours follow the theme, so the only way to keep it honest is to draw it
 * when it changes.
 */
export function drawFavicon(unread: number): void {
  const link = document.getElementById('favicon') as HTMLLinkElement | null;
  if (!link) return;

  const canvas = document.createElement('canvas');
  canvas.width = 32;
  canvas.height = 32;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dark = document.documentElement.dataset.theme === 'dark';
  const fg = dark ? '#f0f0f0' : '#1a1a1a';
  const bg = dark ? '#1a1a1a' : '#f0f0f0';

  ctx.fillStyle = fg;
  if (ctx.roundRect) {
    ctx.beginPath();
    ctx.roundRect(0, 0, 32, 32, 6);
    ctx.fill();
  } else {
    ctx.fillRect(0, 0, 32, 32);
  }

  ctx.fillStyle = bg;
  ctx.font = 'bold 20px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('B', 16, 17);

  if (unread > 0) {
    ctx.fillStyle = '#ef4444';
    ctx.beginPath();
    ctx.arc(24, 8, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    // Three digits at 11px do not fit in a 16px circle.
    ctx.font = `bold ${unread > 99 ? 8 : 11}px system-ui, sans-serif`;
    ctx.fillText(unread > 99 ? '99+' : String(unread), 24, 9);
  }

  // Replace the element; do not mutate it. Chrome repaints the tab when `href`
  // changes on the existing <link>, and Firefox often does not -- it keeps the
  // icon it first parsed, or renders nothing, which is what "the favicon looks
  // broken in Firefox" turned out to be. Swapping the node makes the browser
  // parse a fresh declaration, and the `type` has to change with it: this one
  // is a PNG where the markup declared an SVG.
  const fresh = document.createElement('link');
  fresh.id = 'favicon';
  fresh.rel = 'icon';
  fresh.type = 'image/png';
  fresh.href = canvas.toDataURL('image/png');
  link.replaceWith(fresh);

  // Installed as a PWA, the OS badge is the one people actually see.
  const nav = navigator as Navigator & {
    setAppBadge?: (n?: number) => Promise<void>;
    clearAppBadge?: () => Promise<void>;
  };
  if (unread > 0) nav.setAppBadge?.(unread).catch(() => {});
  else nav.clearAppBadge?.().catch(() => {});
}

/**
 * Ask once, on a real click.
 *
 * Browsers reject a permission prompt that is not tied to a gesture, and one
 * fired on load is the kind of thing people deny reflexively and never revisit.
 */
export function askForNotificationsOnce(): void {
  if (!('Notification' in window) || Notification.permission !== 'default') return;
  const ask = () => {
    void Notification.requestPermission();
    document.body.removeEventListener('click', ask);
  };
  document.body.addEventListener('click', ask, { once: true });
}

/** Alert on articles the server judged worth interrupting for. */
export function notifyHighScores(items: { id: number; title: string }[]): void {
  if (!items.length) return;
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  for (const a of items) {
    // The server returns each article once per reader, so there is no
    // client-side dedupe here to get wrong.
    const n = new Notification('Worth reading', { body: a.title, tag: `article-${a.id}` });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  }
}

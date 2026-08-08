/**
 * "2h", "3d" — how old a story is, in as few characters as possible.
 *
 * Short on purpose: this shares a line with the reading time, the source, the
 * story kind and three 40px buttons, on a 390px screen. "2 hours ago" would not
 * fit and would push something else off.
 *
 * Feeds carry wrong and future publication dates often enough that retention
 * keys on ingest time rather than this, so a date in the future is a real case
 * and renders as "now" rather than a negative.
 */
export function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';

  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return 'now';
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.floor(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h`;
  const days = hours / 24;
  if (days < 7) return `${Math.floor(days)}d`;
  const weeks = days / 7;
  if (weeks < 5) return `${Math.floor(weeks)}w`;
  // Past a month the exact age stops mattering; that it is old is the point.
  return `${Math.floor(days / 30)}mo`;
}

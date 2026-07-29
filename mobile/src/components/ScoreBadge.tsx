import { StyleSheet, Text } from 'react-native';

import { colors, font, radius, space } from '../theme';

/**
 * The score is a 0–1 relevance figure the server already computed; this only
 * chooses how to write it down, matching `_article_card.html`.
 */
export function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  return <Text style={styles.badge}>{Math.round(score * 100)}%</Text>;
}

const styles = StyleSheet.create({
  badge: {
    backgroundColor: colors.accentSoft,
    color: colors.accent,
    fontSize: font.tiny,
    fontWeight: '700',
    borderRadius: radius.sm,
    paddingHorizontal: space.xs + 2,
    paddingVertical: 2,
    overflow: 'hidden',
  },
});

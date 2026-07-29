import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Article } from '@shared/api';

import type { ArticleActions } from '../hooks/useArticleActions';
import { colors, font, radius, space } from '../theme';
import { ActionBar } from './ActionBar';
import { ScoreBadge } from './ScoreBadge';
import { TopicChips } from './TopicChips';

export function ArticleRow({
  article,
  actions,
  onOpen,
}: {
  article: Article;
  actions: ArticleActions;
  onOpen: (article: Article) => void;
}) {
  return (
    <Pressable
      onPress={() => onOpen(article)}
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <View style={styles.left}>
        {article.thumbnail_url ? (
          <Image
            source={{ uri: article.thumbnail_url }}
            style={styles.thumb}
            resizeMode="cover"
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View style={[styles.thumb, styles.thumbEmpty]} />
        )}
        {article.reading_time ? (
          <Text style={styles.readingTime}>{article.reading_time}</Text>
        ) : null}
      </View>

      <View style={styles.body}>
        <View style={styles.titleRow}>
          <ScoreBadge score={article.score} />
          <Text
            style={[styles.title, article.state.read && styles.titleRead]}
            numberOfLines={3}
          >
            {article.title}
          </Text>
        </View>

        {/* Non-null only when de-clickbait actually rewrote the headline, which
            is the server's call, not a comparison done here. */}
        {article.original_title ? (
          <Text style={styles.original} numberOfLines={2}>
            Originally: {article.original_title}
          </Text>
        ) : null}

        {article.duplicate_count > 0 ? (
          <Text style={styles.meta}>
            + {article.duplicate_count} other feed
            {article.duplicate_count === 1 ? '' : 's'}
          </Text>
        ) : null}

        <TopicChips topics={article.topics} />

        {article.summary ? (
          <Text style={styles.summary} numberOfLines={3}>
            {article.summary}
          </Text>
        ) : null}
      </View>

      <ActionBar article={article} actions={actions} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: space.md,
    padding: space.md,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    backgroundColor: colors.bg,
  },
  rowPressed: { backgroundColor: colors.surface },
  left: { width: 72, alignItems: 'center', gap: space.xs },
  thumb: { width: 72, height: 72, borderRadius: radius.md, backgroundColor: colors.surface },
  thumbEmpty: { borderColor: colors.border, borderWidth: StyleSheet.hairlineWidth },
  readingTime: { fontSize: font.tiny, color: colors.muted },
  body: { flex: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-start', gap: space.xs },
  title: { flex: 1, fontSize: font.title, fontWeight: '600', color: colors.text },
  titleRead: { color: colors.muted, fontWeight: '500' },
  original: { fontSize: font.tiny, color: colors.muted, marginTop: 2, fontStyle: 'italic' },
  meta: { fontSize: font.tiny, color: colors.muted, marginTop: 2 },
  summary: { fontSize: font.small, color: colors.muted, marginTop: space.xs, lineHeight: 19 },
});

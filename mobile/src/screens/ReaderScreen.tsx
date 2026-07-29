import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { ArticleDetail } from '@shared/api';

import { ActionBar } from '../components/ActionBar';
import { Banner } from '../components/Banner';
import { Blocks } from '../components/Blocks';
import { ScoreBadge } from '../components/ScoreBadge';
import { TopicChips } from '../components/TopicChips';
import { describeError, isAuthFailure } from '../errors';
import type { MergeArticle } from '../hooks/useArticleActions';
import { useArticleActions } from '../hooks/useArticleActions';
import { useSession } from '../session';
import { colors, font, space } from '../theme';

export function ReaderScreen({
  articleId,
  onClose,
  onArticleChanged,
}: {
  articleId: number;
  onClose: () => void;
  onArticleChanged: MergeArticle;
}) {
  const { client } = useSession();
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Every change here has to reach the list behind the modal too, or closing
  // the reader shows a row that disagrees with what was just tapped.
  const merge = useCallback<MergeArticle>(
    (id, patch) => {
      setDetail((d) => (d && d.id === id ? { ...d, ...patch } : d));
      onArticleChanged(id, patch);
    },
    [onArticleChanged],
  );
  const actions = useArticleActions(client, merge);

  useEffect(() => {
    let alive = true;
    client
      .article(articleId)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
          // The list behind the modal has to learn about the read too. No local
          // correction any more: the server marks it read before reading the card
          // back, so d.state is already right, and patching it here would invent
          // state the response already carries.
          onArticleChanged(d.id, { state: d.state });
      })
      .catch((e: unknown) => {
        if (alive && !isAuthFailure(e)) setError(describeError(e));
      });
    return () => {
      alive = false;
    };
  }, [client, articleId, onArticleChanged]);

  return (
    <View style={styles.container}>
      <View style={styles.bar}>
        <Pressable onPress={onClose} hitSlop={10} accessibilityRole="button">
          <Text style={styles.link}>Close</Text>
        </Pressable>
        {detail ? (
          <ActionBar article={detail} actions={actions} direction="row" />
        ) : (
          <View />
        )}
        <Pressable
          onPress={() => detail && void Linking.openURL(detail.url)}
          hitSlop={10}
          disabled={!detail}
          accessibilityRole="link"
        >
          <Text style={styles.link}>Open ↗</Text>
        </Pressable>
      </View>

      {error ? <Banner message={error} /> : null}
      {actions.error ? (
        <Banner message={actions.error} onDismiss={actions.clearError} />
      ) : null}

      {!detail && !error ? (
        <ActivityIndicator style={styles.spinner} />
      ) : null}

      {detail ? (
        <ScrollView contentContainerStyle={styles.content}>
          <View style={styles.titleRow}>
            <ScoreBadge score={detail.score} />
            {detail.reading_time ? (
              <Text style={styles.meta}>{detail.reading_time}</Text>
            ) : null}
          </View>
          <Text style={styles.title}>{detail.title}</Text>
          {detail.original_title ? (
            <Text style={styles.original}>Originally: {detail.original_title}</Text>
          ) : null}
          <TopicChips topics={detail.topics} />
          {detail.description ? (
            <Text style={styles.description}>{detail.description}</Text>
          ) : null}

          {detail.blocks.length > 0 ? (
            <Blocks groups={detail.blocks} />
          ) : detail.description ? null : (
            <Text style={styles.meta}>Full content not available for this article.</Text>
          )}
        </ScrollView>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  link: { color: colors.accent, fontSize: font.body },
  spinner: { marginTop: space.xl },
  content: { padding: space.lg, paddingBottom: space.xl * 2 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  title: { fontSize: 24, fontWeight: '700', color: colors.text, marginTop: space.sm },
  original: { fontSize: font.small, color: colors.muted, fontStyle: 'italic', marginTop: space.xs },
  description: {
    fontSize: font.body + 2,
    lineHeight: 25,
    color: colors.muted,
    marginTop: space.md,
    marginBottom: space.lg,
  },
  meta: { fontSize: font.small, color: colors.muted },
});

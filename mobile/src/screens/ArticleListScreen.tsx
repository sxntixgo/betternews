import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Article } from '@shared/api';

import { ArticleRow } from '../components/ArticleRow';
import { Banner } from '../components/Banner';
import { useArticleActions } from '../hooks/useArticleActions';
import { useArticles } from '../hooks/useArticles';
import { useSession } from '../session';
import { colors, font, space } from '../theme';
import { ReaderScreen } from './ReaderScreen';

export function ArticleListScreen() {
  const { client, me, signOut } = useSession();
  const list = useArticles(client);
  const actions = useArticleActions(client, list.merge);
  const [openId, setOpenId] = useState<number | null>(null);
  const insets = useSafeAreaInsets();

  const renderItem = useCallback(
    ({ item }: { item: Article }) => (
      <ArticleRow article={item} actions={actions} onOpen={(a) => setOpenId(a.id)} />
    ),
    [actions],
  );

  return (
    <View style={styles.container}>
      <View style={[styles.header, { paddingTop: insets.top + space.sm }]}>
        <View>
          <Text style={styles.heading}>Better News</Text>
          <Text style={styles.who}>Signed in as {me.username}</Text>
        </View>
        <Pressable onPress={signOut} hitSlop={10} accessibilityRole="button">
          <Text style={styles.link}>Sign out</Text>
        </Pressable>
      </View>

      {list.error ? (
        <Banner message={list.error} onDismiss={list.clearError} />
      ) : null}
      {actions.error ? (
        <Banner message={actions.error} onDismiss={actions.clearError} />
      ) : null}

      {list.loading ? (
        <ActivityIndicator style={styles.spinner} />
      ) : (
        <FlatList
          data={list.articles}
          keyExtractor={(a) => String(a.id)}
          renderItem={renderItem}
          refreshControl={
            <RefreshControl refreshing={list.refreshing} onRefresh={list.refresh} />
          }
          // `next_offset` is exact, so paging is simply "ask for the next one".
          onEndReached={list.loadMore}
          onEndReachedThreshold={0.6}
          ListEmptyComponent={
            <Text style={styles.empty}>
              Nothing to read. Pull down to check again.
            </Text>
          }
          ListFooterComponent={
            list.loadingMore ? (
              <ActivityIndicator style={styles.footer} />
            ) : list.atEnd && list.articles.length > 0 ? (
              <Text style={styles.footerText}>That is everything.</Text>
            ) : null
          }
          contentContainerStyle={
            list.articles.length === 0 ? styles.emptyContainer : undefined
          }
        />
      )}

      <Modal
        visible={openId !== null}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setOpenId(null)}
      >
        {openId !== null ? (
          <ReaderScreen
            articleId={openId}
            onClose={() => setOpenId(null)}
            onArticleChanged={list.merge}
          />
        ) : null}
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  heading: { fontSize: 22, fontWeight: '700', color: colors.text },
  who: { fontSize: font.tiny, color: colors.muted },
  link: { color: colors.accent, fontSize: font.small },
  spinner: { marginTop: space.xl },
  empty: { color: colors.muted, fontSize: font.body, textAlign: 'center' },
  emptyContainer: { flexGrow: 1, justifyContent: 'center', padding: space.xl },
  footer: { marginVertical: space.lg },
  footerText: {
    color: colors.muted,
    fontSize: font.tiny,
    textAlign: 'center',
    marginVertical: space.lg,
  },
});

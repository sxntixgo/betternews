import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Article } from '@shared/api';

import type { ActionKind, ArticleActions } from '../hooks/useArticleActions';
import { colors, font, radius, space } from '../theme';

function ActionButton({
  article,
  actions,
  kind,
  label,
  active,
}: {
  article: Article;
  actions: ArticleActions;
  kind: ActionKind;
  label: string;
  active: boolean;
}) {
  const pending = actions.isPending(article.id, kind);
  return (
    <Pressable
      onPress={() => actions.run(article, kind)}
      disabled={pending}
      hitSlop={6}
      accessibilityRole="button"
      accessibilityState={{ selected: active, busy: pending }}
      accessibilityLabel={kind}
      style={[styles.button, active && styles.buttonActive]}
    >
      {pending ? (
        <ActivityIndicator size="small" color={colors.muted} />
      ) : (
        <Text style={styles.label}>{label}</Text>
      )}
    </Pressable>
  );
}

/**
 * Save, like and dislike — the same three the web card offers, driven by the
 * same three endpoints. `state` is whatever the API last said it was.
 */
export function ActionBar({
  article,
  actions,
  direction = 'column',
}: {
  article: Article;
  actions: ArticleActions;
  direction?: 'row' | 'column';
}) {
  const { saved, opinion } = article.state;
  return (
    <View style={[styles.bar, direction === 'row' && styles.barRow]}>
      <ActionButton
        article={article}
        actions={actions}
        kind="save"
        label={saved ? '★' : '☆'}
        active={saved}
      />
      <ActionButton
        article={article}
        actions={actions}
        kind="like"
        label="👍"
        active={opinion === 'liked'}
      />
      <ActionButton
        article={article}
        actions={actions}
        kind="dislike"
        label="👎"
        active={opinion === 'disliked'}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { gap: space.xs, alignItems: 'center' },
  barRow: { flexDirection: 'row', gap: space.md },
  button: {
    minWidth: 34,
    minHeight: 34,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
  },
  buttonActive: { backgroundColor: colors.accentSoft },
  label: { fontSize: font.title },
});

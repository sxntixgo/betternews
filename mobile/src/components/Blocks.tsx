import { useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Block, BlockGroup } from '@shared/api';

import { colors, font, radius, space } from '../theme';

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case 'p':
      return <Text style={styles.paragraph}>{block.text}</Text>;
    case 'ul':
      return (
        <View style={styles.list}>
          {block.items.map((item, i) => (
            <View key={`${i}-${item}`} style={styles.listItem}>
              <Text style={styles.bullet}>{'•'}</Text>
              <Text style={styles.paragraph}>{item}</Text>
            </View>
          ))}
        </View>
      );
    case 'embed':
      // No WebView here, so the embed is a link rather than a rendered card.
      // Dropping it would lose content the server chose to keep.
      return (
        <Pressable
          onPress={() => void Linking.openURL(block.url)}
          style={styles.embed}
          accessibilityRole="link"
        >
          <Text style={styles.embedPlatform}>{block.platform}</Text>
          <Text style={styles.embedUrl} numberOfLines={2}>
            {block.url}
          </Text>
        </Pressable>
      );
  }
}

/**
 * Older-news padding. `remove` mode in the web reader only folds it into a
 * `<details>` — nothing is ever dropped, so a misclassified paragraph is one
 * tap away. This is that `<details>`.
 */
function PaddingGroup({ group }: { group: BlockGroup }) {
  const [open, setOpen] = useState(false);
  const n = group.blocks.length;
  return (
    <View style={styles.padding}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        style={styles.paddingHeader}
      >
        <Text style={styles.paddingLabel}>
          {open ? '▾' : '▸'} {open ? 'Hide' : 'Show'} padding
          {group.label ? ` — ${group.label}` : ''} ({n} block{n === 1 ? '' : 's'})
        </Text>
      </Pressable>
      {open ? (
        <View style={styles.paddingBody}>
          {group.blocks.map((b, i) => (
            <BlockView key={i} block={b} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** The body, exactly as the server classified it. Nothing is re-parsed here. */
export function Blocks({ groups }: { groups: BlockGroup[] }) {
  return (
    <View>
      {groups.map((g, i) =>
        g.aside === null ? (
          <View key={i}>
            {g.blocks.map((b, j) => (
              <BlockView key={j} block={b} />
            ))}
          </View>
        ) : (
          <PaddingGroup key={i} group={g} />
        ),
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  paragraph: {
    flex: 1,
    fontSize: font.body + 1,
    lineHeight: 24,
    color: colors.text,
    marginBottom: space.md,
  },
  list: { marginBottom: space.xs },
  listItem: { flexDirection: 'row', gap: space.sm },
  bullet: { fontSize: font.body + 1, lineHeight: 24, color: colors.muted },
  embed: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: space.md,
    marginBottom: space.md,
    backgroundColor: colors.surface,
  },
  embedPlatform: {
    fontSize: font.tiny,
    textTransform: 'uppercase',
    color: colors.muted,
    marginBottom: 2,
  },
  embedUrl: { fontSize: font.small, color: colors.accent },
  padding: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    marginBottom: space.md,
    overflow: 'hidden',
  },
  paddingHeader: { padding: space.md, backgroundColor: colors.surface },
  paddingLabel: { fontSize: font.small, color: colors.muted },
  paddingBody: { paddingHorizontal: space.md, paddingTop: space.md },
});

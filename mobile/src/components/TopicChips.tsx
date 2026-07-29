import { StyleSheet, Text, View } from 'react-native';

import { colors, font, radius, space } from '../theme';

export function TopicChips({ topics }: { topics: string[] }) {
  if (topics.length === 0) return null;
  return (
    <View style={styles.row}>
      {topics.map((t) => (
        <Text key={t} style={styles.chip}>
          {t}
        </Text>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: space.xs, marginTop: space.xs },
  chip: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    color: colors.muted,
    fontSize: font.tiny,
    paddingHorizontal: space.sm,
    paddingVertical: 2,
    overflow: 'hidden',
  },
});

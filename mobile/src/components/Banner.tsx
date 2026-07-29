import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, font, radius, space } from '../theme';

export function Banner({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <View style={styles.banner}>
      <Text style={styles.text}>{message}</Text>
      {onDismiss ? (
        <Pressable onPress={onDismiss} hitSlop={10} accessibilityLabel="Dismiss">
          <Text style={styles.close}>✕</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    backgroundColor: colors.dangerSoft,
    borderColor: colors.danger,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    margin: space.md,
    padding: space.md,
  },
  text: { flex: 1, color: colors.danger, fontSize: font.small },
  close: { color: colors.danger, fontSize: font.body, paddingHorizontal: space.xs },
});

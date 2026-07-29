import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BetterNewsClient, type Me } from '@shared/api';

import { Banner } from '../components/Banner';
import type { Credentials } from '../credentials';
import { normalizeBaseUrl, saveCredentials } from '../credentials';
import { describeError, isAuthFailure } from '../errors';
import { colors, font, radius, space } from '../theme';

export function SignInScreen({
  initialBaseUrl,
  onSignedIn,
}: {
  initialBaseUrl: string;
  onSignedIn: (creds: Credentials, me: Me) => void;
}) {
  const insets = useSafeAreaInsets();
  const [baseUrl, setBaseUrl] = useState(initialBaseUrl);
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);

  async function submit() {
    const url = normalizeBaseUrl(baseUrl);
    const value = token.trim();
    if (!url || !value) {
      setError('Both the server URL and a token are needed.');
      return;
    }
    setBusy(true);
    setError(null);
    setUsername(null);
    try {
      // Validate before storing. A token that cannot answer /me is not worth
      // putting in the keychain, and the failure belongs on this screen where
      // the fields that caused it are still visible.
      const probe = new BetterNewsClient({ baseUrl: url, getToken: () => value });
      const me = await probe.me();
      setUsername(me.username);
      const creds: Credentials = { baseUrl: url, token: value };
      await saveCredentials(creds);
      onSignedIn(creds, me);
    } catch (e: unknown) {
      setError(
        isAuthFailure(e)
          ? 'That token was rejected. Create a new one under Profile → API tokens.'
          : describeError(e),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={[styles.content, { paddingTop: insets.top + space.xl }]}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.heading}>Better News</Text>
        <Text style={styles.subheading}>
          Point this at your server and paste a token from Profile → API tokens.
        </Text>

        {error ? <Banner message={error} onDismiss={() => setError(null)} /> : null}
        {username ? <Text style={styles.ok}>Signed in as {username}</Text> : null}

        <Text style={styles.label}>Server URL</Text>
        <TextInput
          value={baseUrl}
          onChangeText={setBaseUrl}
          placeholder="http://192.168.1.10:5001"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          inputMode="url"
          style={styles.input}
          editable={!busy}
        />

        <Text style={styles.label}>API token</Text>
        <View style={styles.tokenRow}>
          <TextInput
            value={token}
            onChangeText={setToken}
            placeholder="bn_…"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="off"
            secureTextEntry={!showToken}
            style={[styles.input, styles.flex]}
            editable={!busy}
          />
          <Pressable onPress={() => setShowToken((v) => !v)} hitSlop={8}>
            <Text style={styles.link}>{showToken ? 'Hide' : 'Show'}</Text>
          </Pressable>
        </View>

        <Pressable
          onPress={() => void submit()}
          disabled={busy}
          accessibilityRole="button"
          style={({ pressed }) => [
            styles.submit,
            (busy || pressed) && styles.submitPressed,
          ]}
        >
          {busy ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.submitLabel}>Sign in</Text>
          )}
        </Pressable>

        <Text style={styles.hint}>
          The token is kept in the device keychain, never in plain storage.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: space.lg, gap: space.xs, backgroundColor: colors.bg, flexGrow: 1 },
  heading: { fontSize: 28, fontWeight: '700', color: colors.text },
  subheading: { fontSize: font.small, color: colors.muted, marginBottom: space.lg },
  label: { fontSize: font.small, color: colors.muted, marginTop: space.md },
  input: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: space.md,
    fontSize: font.body,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  tokenRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  link: { color: colors.accent, fontSize: font.small },
  submit: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    padding: space.md,
    alignItems: 'center',
    marginTop: space.xl,
  },
  submitPressed: { opacity: 0.7 },
  submitLabel: { color: '#ffffff', fontSize: font.title, fontWeight: '600' },
  ok: { color: colors.active, fontSize: font.small, marginTop: space.sm },
  hint: { color: colors.muted, fontSize: font.tiny, marginTop: space.lg },
});

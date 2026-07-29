import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

import type { Me } from '@shared/api';

import { createClient } from './src/api';
import type { Credentials } from './src/credentials';
import { clearCredentials, loadCredentials } from './src/credentials';
import { isAuthFailure } from './src/errors';
import { ArticleListScreen } from './src/screens/ArticleListScreen';
import { SignInScreen } from './src/screens/SignInScreen';
import type { Session } from './src/session';
import { SessionProvider } from './src/session';
import { colors } from './src/theme';

type Phase = 'loading' | 'signed-out' | 'signed-in';

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading');
  const [session, setSession] = useState<Session | null>(null);
  // Kept so the sign-in screen comes back pre-filled after a token is revoked;
  // the server URL is not the secret and retyping it is pure friction.
  const [lastBaseUrl, setLastBaseUrl] = useState('');

  const signOut = useCallback(() => {
    setSession(null);
    setPhase('signed-out');
    void clearCredentials();
  }, []);

  // The client is built once and outlives the render that built it, so it must
  // not close over that render's `signOut`.
  const signOutRef = useRef(signOut);
  signOutRef.current = signOut;

  const beginSession = useCallback((creds: Credentials, me: Me) => {
    const client = createClient(creds, () => signOutRef.current());
    setSession({
      client,
      me,
      baseUrl: creds.baseUrl,
      signOut: () => signOutRef.current(),
    });
    setLastBaseUrl(creds.baseUrl);
    setPhase('signed-in');
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const creds = await loadCredentials();
      if (!alive) return;
      if (!creds) {
        setPhase('signed-out');
        return;
      }
      setLastBaseUrl(creds.baseUrl);
      try {
        // Confirm the stored token still works rather than opening a list that
        // would 401 a moment later.
        const probe = createClient(creds, () => signOutRef.current());
        const me = await probe.me();
        if (!alive) return;
        beginSession(creds, me);
      } catch (e: unknown) {
        if (!alive) return;
        // A revoked token is cleared; a server that is merely unreachable keeps
        // its credentials, so a reconnect does not mean retyping them.
        if (isAuthFailure(e)) await clearCredentials();
        if (alive) setPhase('signed-out');
      }
    })();
    return () => {
      alive = false;
    };
  }, [beginSession]);

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <View style={styles.root}>
        {phase === 'loading' ? (
          <ActivityIndicator style={styles.spinner} />
        ) : phase === 'signed-in' && session ? (
          <SessionProvider value={session}>
            <ArticleListScreen />
          </SessionProvider>
        ) : (
          <SignInScreen initialBaseUrl={lastBaseUrl} onSignedIn={beginSession} />
        )}
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  spinner: { flex: 1 },
});

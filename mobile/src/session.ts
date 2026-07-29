import { createContext, useContext } from 'react';

import type { BetterNewsClient, Me } from '@shared/api';

/** A signed-in reader: who they are, and the client that speaks for them. */
export interface Session {
  client: BetterNewsClient;
  me: Me;
  baseUrl: string;
  signOut: () => void;
}

const SessionContext = createContext<Session | null>(null);

export const SessionProvider = SessionContext.Provider;

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession() outside a SessionProvider');
  return session;
}

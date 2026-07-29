# Better News — native client

Expo (React Native + TypeScript) reading client for the Better News API.

**It has never been run on a device.** It type-checks and Metro bundles it for
both platforms; every layout, touch target, gesture and the keychain storage are
unverified. Treat this as a reviewed scaffold, not a working app.

## Run it

```sh
npm install
npx expo start          # then press i / a, or scan the QR with Expo Go
npx tsc --noEmit        # type-check, including ../shared
```

Sign in by pasting the server URL and an API token. Create the token in the web
UI under **Profile → API tokens**; it is shown once.

## Layout

```
App.tsx                     bootstrap, session, sign-out on 401
src/api.ts                  the only place a BetterNewsClient is built
src/credentials.ts          expo-secure-store; a token is a password
src/session.ts              client / me / baseUrl context
src/hooks/                  useArticles (paging), useArticleActions (optimistic)
src/components/             ArticleRow, ActionBar, Blocks, ScoreBadge, TopicChips
src/screens/                SignIn, ArticleList, Reader
```

## Rules this client follows

The server decides what a reader sees; this app renders it. `article.title` is
already the de-clickbaited headline, `original_title` is non-null only when it
really was rewritten, and `blocks` arrive classified. Reimplementing any of that
here is how the phone and the browser start disagreeing — the API exists to stop
it. See `shared/api.ts`, which both clients import.

A block group with a non-null `aside` is older-news padding: it collapses behind
a toggle and is never dropped, matching the web reader.

## The `@shared` alias needs three things

`metro.config.js` needs `watchFolders`, a `resolveRequest` mapping, **and**
`experiments.onDemandFilesystem: false`. Expo's `withMetroMultiPlatform` resets
`watchFolders` to the project root when exporting with the on-demand filesystem
enabled, so `expo start` resolves `@shared/api` while `expo export` fails
claiming the file does not exist. Changing any one of the three breaks the
export but not the dev server.

## Known gaps

- Embeds render as a link; there is no WebView.
- Android release builds against a plain-HTTP server need `expo-build-properties`
  with `usesCleartextTraffic: true`.
- No tests.

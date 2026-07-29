// The API contract lives in ../shared, outside this project, and Metro assumes
// everything it bundles sits under the project root. Three things make the
// alias work, and all three are load-bearing — dropping any one produces a
// build that resolves `@shared/api` and then cannot read the file:
//
//   1. `watchFolders` below, so the directory is crawled and watched;
//   2. `resolveRequest` below, mapping the alias to an absolute path;
//   3. `experiments.onDemandFilesystem: false` in app.json, because
//      `expo export` truncates `watchFolders` back to the project root while
//      that optimisation is on — dev worked and only the production bundle
//      failed, which is the worst order to find out in.
//
// The alias is also declared in tsconfig.json, for the type-checker's benefit.
// Expo's Metro reads tsconfig `paths` too, but that is an experiment that can
// be switched off, and it does not survive (3) either.
const { getDefaultConfig } = require('expo/metro-config');
const path = require('node:path');

const projectRoot = __dirname;
const sharedRoot = path.resolve(projectRoot, '..', 'shared');
const ALIAS = '@shared';

const config = getDefaultConfig(projectRoot);

config.watchFolders = [...(config.watchFolders ?? []), sharedRoot];

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === ALIAS || moduleName.startsWith(`${ALIAS}/`)) {
    const rest = moduleName.slice(ALIAS.length).replace(/^\//, '') || 'api';
    return context.resolveRequest(context, path.join(sharedRoot, rest), platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;

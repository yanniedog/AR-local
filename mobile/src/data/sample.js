// Bundled fallback payload so the app shows real data offline and before the
// first GitHub release is published. These JSON files are generated from a real
// Pi export by `npm run sample` (mobile/scripts/build-sample.mjs). Kept as a .js
// shim (with a matching sample.d.ts) so TypeScript never parses the multi-MB
// JSON literals — Metro still bundles them at build time.
module.exports = {
  sampleManifest: require('../../assets/sample/manifest.json'),
  sampleCore: require('../../assets/sample/core.json'),
  sampleDetails: require('../../assets/sample/details.json'),
};

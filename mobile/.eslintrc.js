// https://docs.expo.dev/guides/using-eslint/
module.exports = {
  root: true,
  extends: ['expo'],
  ignorePatterns: ['/dist/*', '/.expo/*', 'node_modules/*'],
  rules: {
    'import/order': 'off',
  },
};

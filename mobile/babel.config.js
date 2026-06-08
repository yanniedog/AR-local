module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    // Reanimated 4 moved its Babel plugin into react-native-worklets; must be last.
    plugins: ['react-native-worklets/plugin'],
  };
};

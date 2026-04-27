const path = require('path');
const webpack = require('webpack');

const entries = {
  simSettings: './src/webview/simSettings/index.tsx',
  prefillParams: './src/webview/prefillParams/index.tsx',
  replay: './src/webview/replay/index.tsx',
  configPage: './src/webview/configPage/index.tsx',
  initConfig: './src/webview/initConfig/index.tsx',
  skillMarketplace: './src/webview/skillMarketplace/index.tsx',
  helpPage: './src/webview/helpPage/index.tsx',
};

const createConfig = (name, entry) => ({
  target: 'web',
  mode: 'development',
  entry: {
    [name]: entry,
  },
  output: {
    path: path.resolve(__dirname, 'out', 'webview'),
    filename: '[name].js',
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx'],
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: {
            configFile: path.resolve(__dirname, 'src/webview/tsconfig.json'),
          },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader'],
      },
      {
        test: /\.less$/,
        use: [
          'style-loader',
          'css-loader',
          {
            loader: 'less-loader',
            options: {
              lessOptions: {
                javascriptEnabled: true,
              },
            },
          },
        ],
      },
      {
        test: /\.(png|jpg|gif|svg)$/i,
        type: 'asset/inline',
      },
    ],
  },
  devtool: 'source-map',
  optimization: {
    runtimeChunk: false,
    splitChunks: false,
  },
  plugins: [
    new webpack.optimize.LimitChunkCountPlugin({
      maxChunks: 1,
    }),
  ],
  performance: {
    maxAssetSize: 5 * 1024 * 1024,
    maxEntrypointSize: 5 * 1024 * 1024,
    hints: false,
  },
});

module.exports = Object.entries(entries).map(([name, entry]) =>
  createConfig(name, entry)
);

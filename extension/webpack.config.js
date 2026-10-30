const path = require('path');
const webpack = require('webpack');
const TerserPlugin = require('terser-webpack-plugin');

const entries = {
  simSettings: './src/webview/simSettings/index.tsx',
  prefillParams: './src/webview/prefillParams/index.tsx',
  replay: './src/webview/replay/index.tsx',
  configPage: './src/webview/configPage/index.tsx',
  initConfig: './src/webview/initConfig/index.tsx',
  skillMarketplace: './src/webview/skillMarketplace/index.tsx',
  helpPage: './src/webview/helpPage/index.tsx',
};

const isProd = process.env.NODE_ENV === 'production';

const extensionHostConfig = {
  name: 'extensionHost',
  target: 'node',
  mode: isProd ? 'production' : 'development',
  entry: {
    extension: './src/extension.ts',
  },
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: '[name].js',
    libraryTarget: 'commonjs2',
  },
  externals: {
    vscode: 'commonjs vscode',
  },
  resolve: {
    extensions: ['.ts', '.js'],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        use: {
          loader: 'ts-loader',
          options: {
            configFile: path.resolve(__dirname, 'tsconfig.json'),
            transpileOnly: true,
          },
        },
        exclude: /node_modules/,
      },
    ],
  },
  devtool: false,
  optimization: {
    minimize: isProd,
    minimizer: isProd
      ? [
          new TerserPlugin({
            extractComments: false,
          }),
        ]
      : [],
  },
  plugins: [
    // https-proxy-agent exposes Kerberos/SPNEGO as an optional peer. The
    // gateway supports explicit proxy credentials, so preserve the package's
    // runtime "not installed" branch without treating Kerberos as required.
    new webpack.IgnorePlugin({ resourceRegExp: /^kerberos$/ }),
    new webpack.optimize.LimitChunkCountPlugin({
      maxChunks: 1,
    }),
  ],
  performance: {
    hints: false,
  },
};

const createConfig = (name, entry) => ({
  target: 'web',
  mode: isProd ? 'production' : 'development',
  entry: {
    [name]: entry,
  },
  output: {
    path: path.resolve(__dirname, 'out', 'webview'),
    filename: '[name].js',
  },
  cache: {
    type: 'filesystem',
    buildDependencies: {
      config: [__filename],
    },
  },
  parallelism: 2,
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
            transpileOnly: true,
            happyPackMode: true,
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
  devtool: isProd ? false : 'source-map',
  optimization: {
    runtimeChunk: false,
    splitChunks: false,
    minimize: isProd,
    minimizer: isProd
      ? [
          new TerserPlugin({
            extractComments: false,
            terserOptions: {
              format: {
                comments: /@license|@preserve|Copyright/i,
              },
            },
          }),
        ]
      : [],
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

const webviewConfigs = Object.entries(entries).map(([name, entry]) =>
  createConfig(name, entry)
);

module.exports = process.env.WEBPACK_TARGET === 'extension'
  ? [extensionHostConfig]
  : process.env.WEBPACK_TARGET === 'webview'
    ? webviewConfigs
    : [extensionHostConfig, ...webviewConfigs];

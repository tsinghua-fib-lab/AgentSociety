import * as React from 'react';
import * as ReactDOM from 'react-dom/client';
import { HelpPageApp } from './HelpPageApp';
import type { VSCodeAPI } from './types';
import 'antd/dist/reset.css';
import '../i18n';

// Declare global function acquireVsCodeApi
declare function acquireVsCodeApi(): VSCodeAPI;

// Get VSCode API
const vscode: VSCodeAPI = acquireVsCodeApi();

// Render React app
const rootElement = document.getElementById('root');
if (rootElement) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(<HelpPageApp vscode={vscode} />);
} else {
  console.error('Root element not found');
}

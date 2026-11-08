import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { SkillMarketplaceApp } from './SkillMarketplaceApp';
import '../i18n';
import 'antd/dist/reset.css';
import './skillMarketplace.css';

declare function acquireVsCodeApi(): any;

const vscode = acquireVsCodeApi();

const container = document.getElementById('root');
if (container) {
  const root = createRoot(container);
  root.render(<SkillMarketplaceApp vscode={vscode} />);
}

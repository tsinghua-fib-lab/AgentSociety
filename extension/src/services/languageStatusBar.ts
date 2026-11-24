import * as vscode from 'vscode';
import {
  getCurrentLanguageCode,
  localize,
  toggleExtensionLanguage,
  type ExtensionLanguage,
} from '../i18n';

/**
 * 状态栏中英切换入口：只改扩展 UI 文案，不改 VS Code Display Language。
 */
export class LanguageStatusBar {
  private readonly item: vscode.StatusBarItem;

  constructor(context: vscode.ExtensionContext) {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 97);
    this.item.command = 'aiSocialScientist.toggleLanguage';
    context.subscriptions.push(this.item);
    this.refresh();
  }

  refresh(): void {
    const isZh = getCurrentLanguageCode() === 'zh-CN';
    this.item.text = isZh ? '$(globe) 中文' : '$(globe) EN';
    this.item.tooltip = localize('language.toggle.tooltip');
    this.item.show();
  }

  async toggle(): Promise<ExtensionLanguage> {
    return toggleExtensionLanguage();
  }
}
